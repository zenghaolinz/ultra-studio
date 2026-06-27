use futures_util::StreamExt;
use std::time::Duration;
use tauri::{AppHandle, Emitter};

const EVENTS_URL: &str = "http://127.0.0.1:9257/api/generation/tasks/events";

fn extract_sse_data(buffer: &mut Vec<u8>) -> Vec<String> {
    let mut events = Vec::new();
    while let Some(position) = buffer.windows(2).position(|window| window == b"\n\n") {
        let frame = buffer.drain(..position + 2).collect::<Vec<_>>();
        if let Ok(text) = String::from_utf8(frame) {
            for line in text.lines() {
                if let Some(data) = line.strip_prefix("data: ") {
                    events.push(data.to_owned());
                }
            }
        }
    }
    events
}

pub fn spawn_generation_event_bridge(app: AppHandle) {
    tauri::async_runtime::spawn(async move {
        let client = reqwest::Client::new();
        loop {
            let response = client.get(EVENTS_URL).send().await;
            if let Ok(response) = response {
                if response.status().is_success() {
                    let _ = app.emit("generation-task-resync", ());
                    let mut stream = response.bytes_stream();
                    let mut buffer = Vec::new();
                    while let Some(chunk) = stream.next().await {
                        let Ok(chunk) = chunk else { break };
                        buffer.extend_from_slice(&chunk);
                        for data in extract_sse_data(&mut buffer) {
                            let Ok(payload) = serde_json::from_str::<serde_json::Value>(&data)
                            else {
                                continue;
                            };
                            match payload.get("type").and_then(|value| value.as_str()) {
                                Some("task_updated") => {
                                    if let Some(task) = payload.get("task") {
                                        let _ = app.emit("generation-task-updated", task.clone());
                                    }
                                }
                                Some("resync") => {
                                    let _ = app.emit("generation-task-resync", ());
                                }
                                _ => {}
                            }
                        }
                    }
                }
            }
            let _ = app.emit("generation-task-resync", ());
            tokio::time::sleep(Duration::from_secs(2)).await;
        }
    });
}

#[cfg(test)]
mod tests {
    use super::extract_sse_data;

    #[test]
    fn extracts_complete_sse_frames_and_keeps_partial_tail() {
        let mut buffer = b"data: {\"type\":\"task_updated\",\"label\":\"\xe7\x94\x9f\xe6\x88\x90\"}\n\ndata: {\"type\":".to_vec();

        let events = extract_sse_data(&mut buffer);

        assert_eq!(
            events,
            vec!["{\"type\":\"task_updated\",\"label\":\"生成\"}"]
        );
        assert_eq!(buffer, b"data: {\"type\":".to_vec());
    }
}
