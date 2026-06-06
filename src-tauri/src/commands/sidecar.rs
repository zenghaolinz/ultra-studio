use reqwest::Client;
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, State};
use tokio::sync::Mutex;
use futures_util::StreamExt;
use std::fs;
use std::path::Path;
use std::process::Command;
use std::time::Duration;

const SIDECAR_URL: &str = "http://127.0.0.1:9257";

fn response_excerpt(body: &str) -> String {
    body.chars().take(500).collect()
}

#[cfg(test)]
mod tests {
    use super::response_excerpt;

    #[test]
    fn response_excerpt_truncates_unicode_on_character_boundaries() {
        let body = "\u{4e2d}".repeat(600);
        let excerpt = response_excerpt(&body);

        assert_eq!(excerpt.chars().count(), 500);
        assert!(body.starts_with(&excerpt));
    }
}

pub struct SidecarState {
    pub client: Client,
    pub ready: Mutex<bool>,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct Conversation {
    pub id: String,
    pub title: String,
    #[serde(rename = "projectId")]
    pub project_id: Option<String>,
    #[serde(rename = "createdAt")]
    pub created_at: String,
    #[serde(rename = "updatedAt")]
    pub updated_at: String,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct Project {
    pub id: String,
    pub name: String,
    #[serde(rename = "rootPath")]
    pub root_path: String,
    #[serde(rename = "createdAt")]
    pub created_at: String,
    #[serde(rename = "updatedAt")]
    pub updated_at: String,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct ProjectVisibleFile {
    pub name: String,
    pub path: String,
    #[serde(rename = "relativePath")]
    pub relative_path: String,
    pub extension: String,
    pub size: i64,
    #[serde(rename = "modifiedAt")]
    pub modified_at: String,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct ProjectFileSummary {
    #[serde(rename = "rootPath")]
    pub root_path: String,
    pub documents: Vec<ProjectVisibleFile>,
    pub images: Vec<ProjectVisibleFile>,
    #[serde(rename = "documentCount")]
    pub document_count: i64,
    #[serde(rename = "imageCount")]
    pub image_count: i64,
    #[serde(rename = "scannedCount")]
    pub scanned_count: i64,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct Message {
    pub id: String,
    #[serde(rename = "conversationId")]
    pub conversation_id: String,
    pub role: String,
    pub content: String,
    #[serde(rename = "createdAt")]
    pub created_at: String,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct ModelConfig {
    pub id: String,
    pub provider: String,
    #[serde(rename = "modelName")]
    pub model_name: String,
    #[serde(rename = "apiKey")]
    pub api_key: String,
    #[serde(rename = "baseUrl")]
    pub base_url: String,
    #[serde(rename = "isDefault")]
    pub is_default: bool,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct EmbeddingConfig {
    pub id: String,
    pub provider: String,
    #[serde(rename = "modelName")]
    pub model_name: String,
    pub dimensions: i32,
    #[serde(rename = "apiKey")]
    pub api_key: String,
    #[serde(rename = "baseUrl")]
    pub base_url: String,
    #[serde(rename = "isDefault")]
    pub is_default: bool,
}

#[tauri::command]
pub async fn init_sidecar(state: State<'_, SidecarState>) -> Result<bool, String> {
    let client = &state.client;
    match client.get(format!("{}/api/config/models", SIDECAR_URL)).send().await {
        Ok(resp) if resp.status().is_success() => {
            let mut ready = state.ready.lock().await;
            *ready = true;
            Ok(true)
        }
        Ok(resp) => Err(format!("Sidecar health check failed: HTTP {}", resp.status())),
        Err(_) => Err("Sidecar not ready. Please start the Python sidecar first.".into()),
    }
}

#[tauri::command]
pub async fn list_projects(state: State<'_, SidecarState>) -> Result<Vec<Project>, String> {
    check_ready(&state)?;
    let client = &state.client;
    let resp = client
        .get(format!("{}/api/chat/projects", SIDECAR_URL))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    let projects: Vec<Project> = resp.json().await.map_err(|e| e.to_string())?;
    Ok(projects)
}

#[tauri::command]
pub async fn create_project(state: State<'_, SidecarState>, path: String, name: Option<String>) -> Result<Project, String> {
    check_ready(&state)?;
    let client = &state.client;
    let resp = client
        .post(format!("{}/api/chat/projects", SIDECAR_URL))
        .json(&serde_json::json!({ "path": path, "name": name }))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    let status = resp.status();
    if !status.is_success() {
        let body = resp.text().await.unwrap_or_else(|_| "Unknown error".into());
        return Err(format!("Create project failed ({}): {}", status, body));
    }
    let project: Project = resp.json().await.map_err(|e| e.to_string())?;
    Ok(project)
}

#[tauri::command]
pub async fn delete_project(state: State<'_, SidecarState>, project_id: String) -> Result<bool, String> {
    check_ready(&state)?;
    let client = &state.client;
    client
        .delete(format!("{}/api/chat/projects/{}", SIDECAR_URL, project_id))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    Ok(true)
}

#[tauri::command]
pub async fn list_project_files(state: State<'_, SidecarState>, project_id: String) -> Result<ProjectFileSummary, String> {
    check_ready(&state)?;
    let client = &state.client;
    let resp = client
        .get(format!("{}/api/chat/projects/{}/files", SIDECAR_URL, project_id))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    let status = resp.status();
    if !status.is_success() {
        let body = resp.text().await.unwrap_or_else(|_| "Unknown error".into());
        return Err(format!("List project files failed ({}): {}", status, body));
    }
    let files: ProjectFileSummary = resp.json().await.map_err(|e| e.to_string())?;
    Ok(files)
}

#[tauri::command]
pub async fn list_conversations(state: State<'_, SidecarState>, project_id: Option<String>) -> Result<Vec<Conversation>, String> {
    check_ready(&state)?;
    let client = &state.client;
    let mut request = client.get(format!("{}/api/chat/conversations", SIDECAR_URL));
    if let Some(id) = project_id {
        request = request.query(&[("project_id", id)]);
    }
    let resp = request.send().await.map_err(|e| e.to_string())?;
    let convs: Vec<Conversation> = resp.json().await.map_err(|e| e.to_string())?;
    Ok(convs)
}

#[tauri::command]
pub async fn create_conversation(state: State<'_, SidecarState>, title: String, project_id: Option<String>) -> Result<Conversation, String> {
    check_ready(&state)?;
    let client = &state.client;
    let resp = client
        .post(format!("{}/api/chat/conversations", SIDECAR_URL))
        .json(&serde_json::json!({ "title": title, "project_id": project_id }))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    let conv: Conversation = resp.json().await.map_err(|e| e.to_string())?;
    Ok(conv)
}

#[tauri::command]
pub async fn delete_conversation(state: State<'_, SidecarState>, conversation_id: String) -> Result<bool, String> {
    check_ready(&state)?;
    let client = &state.client;
    client
        .delete(format!("{}/api/chat/conversations/{}", SIDECAR_URL, conversation_id))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    Ok(true)
}

#[tauri::command]
pub async fn get_messages(state: State<'_, SidecarState>, conversation_id: String) -> Result<Vec<Message>, String> {
    check_ready(&state)?;
    let client = &state.client;
    let resp = client
        .get(format!("{}/api/chat/conversations/{}/messages", SIDECAR_URL, conversation_id))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    let msgs: Vec<Message> = resp.json().await.map_err(|e| e.to_string())?;
    Ok(msgs)
}

#[tauri::command]
pub async fn send_message(
    state: State<'_, SidecarState>,
    conversation_id: String,
    content: String,
    image_paths: Option<Vec<String>>,
    permission_mode: Option<String>,
    project_path: Option<String>,
    model_id: Option<String>,
    vision_enabled: Option<bool>,
    hidden_user_message: Option<bool>,
    remove_message_id: Option<String>,
) -> Result<Message, String> {
    check_ready(&state)?;
    let client = &state.client;
    let mut body = serde_json::json!({
        "conversation_id": conversation_id,
        "content": content,
        "permission_mode": permission_mode.unwrap_or_else(|| "standard".into()),
        "project_path": project_path,
        "model_id": model_id,
        "vision_enabled": vision_enabled.unwrap_or(false),
        "hidden_user_message": hidden_user_message.unwrap_or(false),
        "remove_message_id": remove_message_id
    });
    if let Some(paths) = &image_paths {
        if !paths.is_empty() {
            body["image_paths"] = serde_json::json!(paths);
        }
    }
    let resp = client
        .post(format!("{}/api/chat/send", SIDECAR_URL))
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;

    let status = resp.status();
    if !status.is_success() {
        let body = resp.text().await.unwrap_or_else(|_| "Unknown error".into());
        return Err(format!("Sidecar error ({}): {}", status, body));
    }

    let msg: Message = resp.json().await.map_err(|e| format!("Parse error: {}", e))?;
    Ok(msg)
}

#[tauri::command]
pub async fn send_stream_start(
    app: AppHandle,
    state: State<'_, SidecarState>,
    conversation_id: String,
    content: String,
    image_paths: Option<Vec<String>>,
    permission_mode: Option<String>,
    project_path: Option<String>,
    model_id: Option<String>,
    vision_enabled: Option<bool>,
    hidden_user_message: Option<bool>,
    remove_message_id: Option<String>,
) -> Result<bool, String> {
    check_ready(&state)?;

    let client = state.client.clone();
    let app_clone = app.clone();
    let conv_id_for_events = conversation_id.clone();
    let conv_id_for_title = conversation_id.clone();

    let mut body = serde_json::json!({
        "conversation_id": conv_id_for_title,
        "content": content,
        "permission_mode": permission_mode.unwrap_or_else(|| "standard".into()),
        "project_path": project_path,
        "model_id": model_id,
        "vision_enabled": vision_enabled.unwrap_or(false),
        "hidden_user_message": hidden_user_message.unwrap_or(false),
        "remove_message_id": remove_message_id
    });
    if let Some(paths) = &image_paths {
        if !paths.is_empty() {
            body["image_paths"] = serde_json::json!(paths);
        }
    }

    tokio::spawn(async move {
        let resp = client
            .post(format!("{}/api/chat/send/stream", SIDECAR_URL))
            .json(&body)
            .send()
            .await;

        match resp {
            Ok(resp) => {
                let status = resp.status();
                if !status.is_success() {
                    let body = resp.text().await.unwrap_or_else(|_| "Unknown error".into());
                    let _ = app_clone.emit("chat-error", serde_json::json!({"conversationId": conv_id_for_events.clone(), "error": format!("HTTP {}: {}", status, body)}));
                    return;
                }

                let mut stream = resp.bytes_stream();
                let mut byte_buf: Vec<u8> = Vec::new();

                while let Some(chunk_result) = stream.next().await {
                    match chunk_result {
                        Ok(bytes) => {
                            byte_buf.extend_from_slice(&bytes);
                            while let Some(pos) = byte_buf.windows(2).position(|w| w == b"\n\n") {
                                let event_bytes = byte_buf[..pos].to_vec();
                                byte_buf.drain(..pos + 2);

                                let event_str = match String::from_utf8(event_bytes) {
                                    Ok(s) => s,
                                    Err(_) => continue,
                                };

                                for line in event_str.lines() {
                                    if let Some(data) = line.strip_prefix("data: ") {
                                        let data = data.trim();
                                        if data == "[DONE]" {
                                            let _ = app_clone.emit("chat-done", serde_json::json!({}));
                                            return;
                                        }
                                        match serde_json::from_str::<serde_json::Value>(data) {
                                            Ok(json_val) => {
                                                let mut event_val = json_val;
                                                if let serde_json::Value::Object(ref mut obj) = event_val {
                                                    obj.insert("conversationId".into(), serde_json::Value::String(conv_id_for_events.clone()));
                                                }
                                                if event_val.get("token").is_some() {
                                                    let _ = app_clone.emit("chat-chunk", event_val);
                                                } else if event_val.get("status").is_some() {
                                                    let _ = app_clone.emit("chat-status", event_val);
                                                } else if event_val.get("done").is_some() {
                                                    let _ = app_clone.emit("chat-done", event_val);
                                                    return;
                                                } else if event_val.get("error").is_some() {
                                                    let _ = app_clone.emit("chat-error", event_val);
                                                    return;
                                                }
                                            }
                                            Err(_) => {}
                                        }
                                    }
                                }
                            }
                        }
                        Err(e) => {
                            let _ = app_clone.emit("chat-error", serde_json::json!({"conversationId": conv_id_for_events, "error": e.to_string()}));
                            return;
                        }
                    }
                }
                let _ = app_clone.emit("chat-done", serde_json::json!({"conversationId": conv_id_for_events}));
            }
            Err(e) => {
                let _ = app_clone.emit("chat-error", serde_json::json!({"conversationId": conv_id_for_events, "error": e.to_string()}));
            }
        }
    });

    Ok(true)
}

#[tauri::command]
pub async fn update_conversation_title(
    state: State<'_, SidecarState>,
    conversation_id: String,
    title: String,
) -> Result<Conversation, String> {
    check_ready(&state)?;
    let client = &state.client;
    let resp = client
        .put(format!("{}/api/chat/conversations/{}/title", SIDECAR_URL, conversation_id))
        .json(&serde_json::json!({ "title": title }))
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;

    let status = resp.status();
    if !status.is_success() {
        let body = resp.text().await.unwrap_or_else(|_| "Unknown error".into());
        return Err(format!("Update title error ({}): {}", status, body));
    }

    let updated: serde_json::Value = resp.json().await.map_err(|e| format!("Parse error: {}", e))?;

    let conversations_resp = client
        .get(format!("{}/api/chat/conversations", SIDECAR_URL))
        .send()
        .await
        .map_err(|e| format!("Refresh error: {}", e))?;
    let _convs: Vec<Conversation> = conversations_resp.json().await.map_err(|e| format!("Parse error: {}", e))?;

    Ok(Conversation {
        id: conversation_id,
        title: updated["title"].as_str().unwrap_or(&title).to_string(),
        project_id: None,
        created_at: String::new(),
        updated_at: updated["updatedAt"].as_str().unwrap_or("").to_string(),
    })
}

#[derive(Serialize, Deserialize, Debug)]
pub struct LocalModel {
    pub id: String,
    pub name: String,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct LocalProvider {
    pub name: String,
    #[serde(rename = "baseUrl")]
    pub base_url: String,
    pub available: bool,
    pub models: Vec<LocalModel>,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct ComfyUiStatus {
    pub started: Option<bool>,
    pub stopped: Option<bool>,
    pub running: Option<bool>,
    pub ready: Option<bool>,
    #[serde(rename = "configured_path")]
    pub configured_path: Option<String>,
    #[serde(rename = "launch_mode")]
    pub launch_mode: Option<String>,
    #[serde(rename = "selected_profile_id")]
    pub selected_profile_id: Option<String>,
    #[serde(rename = "process_alive")]
    pub process_alive: Option<bool>,
    #[serde(rename = "recent_logs")]
    pub recent_logs: Option<Vec<String>>,
    pub error: Option<String>,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct ComfyUiProfile {
    pub id: String,
    pub name: String,
    pub path: String,
    #[serde(rename = "launch_mode")]
    pub launch_mode: Option<String>,
    pub selected: Option<bool>,
    pub valid: Option<bool>,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct ComfyUiProfilesResponse {
    pub profiles: Vec<ComfyUiProfile>,
    pub status: ComfyUiStatus,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct ComfyUiProfileSaveRequest {
    pub id: Option<String>,
    pub name: String,
    pub path: String,
    pub select: bool,
    #[serde(rename = "launchMode")]
    pub launch_mode: Option<String>,
}

#[tauri::command]
pub async fn get_comfyui_status(state: State<'_, SidecarState>) -> Result<ComfyUiStatus, String> {
    let client = &state.client;
    let resp = client
        .get(format!("{}/api/comfyui/status", SIDECAR_URL))
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;
    let status: ComfyUiStatus = resp.json().await.map_err(|e| format!("Parse error: {}", e))?;
    Ok(status)
}

#[tauri::command]
pub async fn list_comfyui_profiles(state: State<'_, SidecarState>) -> Result<ComfyUiProfilesResponse, String> {
    let client = &state.client;
    let resp = client
        .get(format!("{}/api/comfyui/profiles", SIDECAR_URL))
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;
    let profiles: ComfyUiProfilesResponse = resp.json().await.map_err(|e| format!("Parse error: {}", e))?;
    Ok(profiles)
}

#[tauri::command]
pub async fn save_comfyui_profile(
    state: State<'_, SidecarState>,
    profile: ComfyUiProfileSaveRequest,
) -> Result<ComfyUiProfilesResponse, String> {
    let client = &state.client;
    let resp = client
        .post(format!("{}/api/comfyui/profiles", SIDECAR_URL))
        .json(&profile)
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;
    let status = resp.status();
    let body = resp.text().await.unwrap_or_else(|_| "Unknown error".into());
    if !status.is_success() {
        return Err(format!("Save ComfyUI profile failed ({}): {}", status, body));
    }
    serde_json::from_str(&body).map_err(|e| format!("Parse error: {}", e))
}

#[tauri::command]
pub async fn select_comfyui_profile(state: State<'_, SidecarState>, id: String) -> Result<ComfyUiProfilesResponse, String> {
    let client = &state.client;
    let resp = client
        .put(format!("{}/api/comfyui/profiles/select", SIDECAR_URL))
        .json(&serde_json::json!({ "id": id }))
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;
    let status = resp.status();
    let body = resp.text().await.unwrap_or_else(|_| "Unknown error".into());
    if !status.is_success() {
        return Err(format!("Select ComfyUI profile failed ({}): {}", status, body));
    }
    serde_json::from_str(&body).map_err(|e| format!("Parse error: {}", e))
}

#[tauri::command]
pub async fn start_comfyui(state: State<'_, SidecarState>) -> Result<ComfyUiStatus, String> {
    let client = &state.client;
    let resp = client
        .post(format!("{}/api/comfyui/start", SIDECAR_URL))
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;
    let status: ComfyUiStatus = resp.json().await.map_err(|e| format!("Parse error: {}", e))?;
    Ok(status)
}

#[tauri::command]
pub async fn stop_comfyui(state: State<'_, SidecarState>) -> Result<ComfyUiStatus, String> {
    let client = &state.client;
    let resp = client
        .post(format!("{}/api/comfyui/stop", SIDECAR_URL))
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;
    let status: ComfyUiStatus = resp.json().await.map_err(|e| format!("Parse error: {}", e))?;
    Ok(status)
}

#[tauri::command]
pub async fn detect_local_models(state: State<'_, SidecarState>) -> Result<Vec<LocalProvider>, String> {
    check_ready(&state)?;
    let client = &state.client;
    let resp = client
        .get(format!("{}/api/config/detect-local", SIDECAR_URL))
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;
    let providers: Vec<LocalProvider> = resp.json().await.map_err(|e| format!("Parse error: {}", e))?;
    Ok(providers)
}

#[tauri::command]
pub async fn get_diagnostics(state: State<'_, SidecarState>) -> Result<serde_json::Value, String> {
    check_ready(&state)?;
    let client = &state.client;
    let resp = client
        .get(format!("{}/api/config/diagnostics", SIDECAR_URL))
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;
    let status = resp.status();
    let body = resp.text().await.unwrap_or_else(|_| "Unknown error".into());
    if !status.is_success() {
        return Err(format!("Diagnostics failed ({}): {}", status, body));
    }
    serde_json::from_str(&body).map_err(|e| format!("Parse error: {}", e))
}

#[tauri::command]
pub async fn list_model_configs(state: State<'_, SidecarState>) -> Result<Vec<ModelConfig>, String> {
    check_ready(&state)?;
    let client = &state.client;
    let resp = client
        .get(format!("{}/api/config/models", SIDECAR_URL))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    let configs: Vec<ModelConfig> = resp.json().await.map_err(|e| e.to_string())?;
    Ok(configs)
}

#[tauri::command]
pub async fn add_model_config(state: State<'_, SidecarState>, config: ModelConfig) -> Result<ModelConfig, String> {
    check_ready(&state)?;
    let client = &state.client;
    let body = serde_json::json!({
        "provider": config.provider,
        "model_name": config.model_name,
        "api_key": config.api_key,
        "base_url": config.base_url,
        "is_default": config.is_default,
    });
    let resp = client
        .post(format!("{}/api/config/models", SIDECAR_URL))
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;

    let status = resp.status();
    if !status.is_success() {
        let text = resp.text().await.unwrap_or_else(|_| "Unknown error".into());
        return Err(format!("Add model failed ({}): {}", status, text));
    }

    let result: ModelConfig = resp.json().await.map_err(|e| format!("Parse error: {}", e))?;
    Ok(result)
}

#[tauri::command]
pub async fn remove_model_config(state: State<'_, SidecarState>, id: String) -> Result<bool, String> {
    check_ready(&state)?;
    let client = &state.client;
    client
        .delete(format!("{}/api/config/models/{}", SIDECAR_URL, id))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    Ok(true)
}

#[tauri::command]
pub async fn set_default_model_config(state: State<'_, SidecarState>, id: String) -> Result<ModelConfig, String> {
    check_ready(&state)?;
    let client = &state.client;
    let resp = client
        .put(format!("{}/api/config/models/{}/default", SIDECAR_URL, id))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    let status = resp.status();
    if !status.is_success() {
        let text = resp.text().await.unwrap_or_else(|_| "Unknown error".into());
        return Err(format!("Set default model failed ({}): {}", status, text));
    }
    let config: ModelConfig = resp.json().await.map_err(|e| e.to_string())?;
    Ok(config)
}

#[tauri::command]
pub async fn list_embedding_configs(state: State<'_, SidecarState>) -> Result<Vec<EmbeddingConfig>, String> {
    check_ready(&state)?;
    let client = &state.client;
    let resp = client
        .get(format!("{}/api/config/embeddings", SIDECAR_URL))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    let configs: Vec<EmbeddingConfig> = resp.json().await.map_err(|e| e.to_string())?;
    Ok(configs)
}

#[tauri::command]
pub async fn add_embedding_config(state: State<'_, SidecarState>, config: EmbeddingConfig) -> Result<EmbeddingConfig, String> {
    check_ready(&state)?;
    let client = &state.client;
    let body = serde_json::json!({
        "provider": config.provider,
        "model_name": config.model_name,
        "dimensions": config.dimensions,
        "api_key": config.api_key,
        "base_url": config.base_url,
        "is_default": config.is_default,
    });
    let resp = client
        .post(format!("{}/api/config/embeddings", SIDECAR_URL))
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;

    let status = resp.status();
    if !status.is_success() {
        let text = resp.text().await.unwrap_or_else(|_| "Unknown error".into());
        return Err(format!("Add embedding failed ({}): {}", status, text));
    }

    let result: EmbeddingConfig = resp.json().await.map_err(|e| format!("Parse error: {}", e))?;
    Ok(result)
}

#[tauri::command]
pub async fn remove_embedding_config(state: State<'_, SidecarState>, id: String) -> Result<bool, String> {
    check_ready(&state)?;
    let client = &state.client;
    client
        .delete(format!("{}/api/config/embeddings/{}", SIDECAR_URL, id))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    Ok(true)
}

#[derive(Serialize, Deserialize, Debug)]
pub struct Persona {
    pub content: String,
    #[serde(rename = "updatedAt")]
    pub updated_at: String,
}

#[tauri::command]
pub async fn get_persona(state: State<'_, SidecarState>) -> Result<Persona, String> {
    check_ready(&state)?;
    let client = &state.client;
    let resp = client
        .get(format!("{}/api/config/persona", SIDECAR_URL))
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;
    let persona: Persona = resp.json().await.map_err(|e| format!("Parse error: {}", e))?;
    Ok(persona)
}

#[tauri::command]
pub async fn update_persona(state: State<'_, SidecarState>, content: String) -> Result<Persona, String> {
    check_ready(&state)?;
    let client = &state.client;
    let resp = client
        .put(format!("{}/api/config/persona", SIDECAR_URL))
        .json(&serde_json::json!({ "content": content }))
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;

    let status = resp.status();
    if !status.is_success() {
        let body = resp.text().await.unwrap_or_else(|_| "Unknown error".into());
        return Err(format!("Update persona error ({}): {}", status, body));
    }

    let persona: Persona = resp.json().await.map_err(|e| format!("Parse error: {}", e))?;
    Ok(persona)
}

#[derive(Serialize, Deserialize, Debug)]
pub struct RememberResult {
    pub ok: bool,
    pub id: Option<String>,
    pub content: Option<String>,
    #[serde(rename = "branchPath")]
    pub branch_path: Option<String>,
    pub tags: Option<Vec<String>>,
    pub error: Option<String>,
}

#[tauri::command]
pub async fn remember_memory(
    state: State<'_, SidecarState>,
    content: String,
    branch_path: Option<String>,
    tags: Option<Vec<String>>,
) -> Result<RememberResult, String> {
    check_ready(&state)?;
    let client = &state.client;
    let mut body = serde_json::json!({ "content": content });
    if let Some(bp) = branch_path {
        body["branch_path"] = serde_json::json!(bp);
    }
    if let Some(t) = tags {
        body["tags"] = serde_json::json!(t);
    }
    let resp = client
        .post(format!("{}/api/memory/remember", SIDECAR_URL))
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;

    let status = resp.status();
    if !status.is_success() {
        let body_text = resp.text().await.unwrap_or_else(|_| "Unknown error".into());
        return Err(format!("Remember failed ({}): {}", status, body_text));
    }

    let result: RememberResult = resp.json().await.map_err(|e| format!("Parse error: {}", e))?;
    Ok(result)
}

fn check_ready(state: &State<'_, SidecarState>) -> Result<(), String> {
    let ready = state.ready.try_lock();
    match ready {
        Ok(guard) => {
            if *guard {
                Ok(())
            } else {
                Err("Sidecar not initialized".into())
            }
        }
        Err(_) => Err("Sidecar state locked".into()),
    }
}

// ============================================================
// 3D Generation Commands
// ============================================================

#[derive(Serialize, Deserialize, Debug)]
pub struct ThreeDResult {
    pub status: String,
    #[serde(rename = "modelPath")]
    pub model_path: Option<String>,
    #[serde(rename = "image2D")]
    pub image_2d: Option<String>,
    #[serde(rename = "imageNormal")]
    pub image_normal: Option<String>,
    #[serde(rename = "imageUV")]
    pub image_uv: Option<String>,
    #[serde(rename = "image1Path")]
    pub image1_path: Option<String>,
    #[serde(rename = "image2Path")]
    pub image2_path: Option<String>,
    pub message: Option<String>,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct ImageGenerateResult {
    pub status: String,
    #[serde(rename = "imagePath")]
    pub image_path: Option<String>,
    pub message: Option<String>,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct MultiviewImageResult {
    pub status: String,
    #[serde(rename = "frontPath")]
    pub front_path: Option<String>,
    #[serde(rename = "leftPath")]
    pub left_path: Option<String>,
    #[serde(rename = "backPath")]
    pub back_path: Option<String>,
    pub message: Option<String>,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct VideoGenerateResult {
    pub status: String,
    #[serde(rename = "videoPath")]
    pub video_path: Option<String>,
    pub message: Option<String>,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct ShowcaseMaterialResult {
    pub status: String,
    pub path: Option<String>,
    pub message: Option<String>,
}

#[tauri::command]
pub async fn generate_3d_text(
    state: State<'_, SidecarState>,
    prompt: String,
    quality: Option<String>,
) -> Result<ThreeDResult, String> {
    let client = &state.client;
    let q = quality.unwrap_or_else(|| "fast".into());
    let resp = client
        .post(format!("{}/api/3d/generate/text", SIDECAR_URL))
        .json(&serde_json::json!({ "prompt": prompt, "quality_mode": q }))
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;
    let status = resp.status();
    let body = resp.text().await.unwrap_or_else(|_| "Unknown error".into());
    if !status.is_success() {
        return Err(format!("Sidecar error ({}): {}", status, body));
    }
    let result: ThreeDResult = serde_json::from_str(&body)
        .map_err(|e| format!("Parse error: {} - body: {}", e, response_excerpt(&body)))?;
    Ok(result)
}

#[tauri::command]
pub async fn generate_3d_image(
    state: State<'_, SidecarState>,
    image_path: String,
    quality: Option<String>,
) -> Result<ThreeDResult, String> {
    let client = &state.client;
    let q = quality.unwrap_or_else(|| "fast".into());
    let resp = client
        .post(format!("{}/api/3d/generate/image", SIDECAR_URL))
        .json(&serde_json::json!({ "image_path": image_path, "quality_mode": q }))
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;
    let status = resp.status();
    let body = resp.text().await.unwrap_or_else(|_| "Unknown error".into());
    if !status.is_success() {
        return Err(format!("Sidecar error ({}): {}", status, body));
    }
    let result: ThreeDResult = serde_json::from_str(&body)
        .map_err(|e| format!("Parse error: {} - body: {}", e, response_excerpt(&body)))?;
    Ok(result)
}

#[tauri::command]
pub async fn generate_3d_fusion(
    state: State<'_, SidecarState>,
    image1_path: String,
    image2_path: String,
    prompt: String,
    quality: Option<String>,
) -> Result<ThreeDResult, String> {
    let client = &state.client;
    let q = quality.unwrap_or_else(|| "fast".into());
    let resp = client
        .post(format!("{}/api/3d/generate/fusion", SIDECAR_URL))
        .json(&serde_json::json!({
            "image1_path": image1_path,
            "image2_path": image2_path,
            "prompt": prompt,
            "quality_mode": q,
        }))
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;
    let status = resp.status();
    let body = resp.text().await.unwrap_or_else(|_| "Unknown error".into());
    if !status.is_success() {
        return Err(format!("Sidecar error ({}): {}", status, body));
    }
    let result: ThreeDResult = serde_json::from_str(&body)
        .map_err(|e| format!("Parse error: {} - body: {}", e, response_excerpt(&body)))?;
    Ok(result)
}

#[tauri::command]
pub async fn generate_3d_multiview(
    state: State<'_, SidecarState>,
    image_paths: Vec<String>,
    quality: Option<String>,
) -> Result<ThreeDResult, String> {
    let client = &state.client;
    let q = quality.unwrap_or_else(|| "fast".into());
    let resp = client
        .post(format!("{}/api/3d/generate/multiview", SIDECAR_URL))
        .json(&serde_json::json!({ "image_paths": image_paths, "quality_mode": q }))
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;
    let status = resp.status();
    let body = resp.text().await.unwrap_or_else(|_| "Unknown error".into());
    if !status.is_success() {
        return Err(format!("Sidecar error ({}): {}", status, body));
    }
    let result: ThreeDResult = serde_json::from_str(&body)
        .map_err(|e| format!("Parse error: {} - body: {}", e, response_excerpt(&body)))?;
    Ok(result)
}

#[tauri::command]
pub async fn generate_3d_improve_image(
    state: State<'_, SidecarState>,
    image_path: String,
    improvement_prompt: String,
    quality: Option<String>,
    image_lora_id: Option<String>,
) -> Result<ThreeDResult, String> {
    let client = &state.client;
    let q = quality.unwrap_or_else(|| "fast".into());
    let resp = client
        .post(format!("{}/api/3d/improve-image", SIDECAR_URL))
        .json(&serde_json::json!({
            "image_path": image_path,
            "improvement_prompt": improvement_prompt,
            "quality_mode": q,
            "image_lora_id": image_lora_id,
        }))
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;
    let status = resp.status();
    let body = resp.text().await.unwrap_or_else(|_| "Unknown error".into());
    if !status.is_success() {
        return Err(format!("Sidecar error ({}): {}", status, body));
    }
    let result: ThreeDResult = serde_json::from_str(&body)
        .map_err(|e| format!("Parse error: {} - body: {}", e, response_excerpt(&body)))?;
    Ok(result)
}

#[tauri::command]
pub async fn generate_flux_image(
    state: State<'_, SidecarState>,
    prompt: String,
    quality: Option<String>,
    image_lora_id: Option<String>,
) -> Result<ImageGenerateResult, String> {
    let client = &state.client;
    let q = quality.unwrap_or_else(|| "fast".into());
    let resp = client
        .post(format!("{}/api/3d/generate-image", SIDECAR_URL))
        .json(&serde_json::json!({
            "prompt": prompt,
            "quality_mode": q,
            "image_lora_id": image_lora_id,
        }))
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;
    let status = resp.status();
    let body = resp.text().await.unwrap_or_else(|_| "Unknown error".into());
    if !status.is_success() {
        return Err(format!("Sidecar error ({}): {}", status, body));
    }
    serde_json::from_str(&body).map_err(|e| format!("Parse error: {} - body: {}", e, response_excerpt(&body)))
}

#[tauri::command]
pub async fn list_image_loras(
    state: State<'_, SidecarState>,
    quality: Option<String>,
) -> Result<serde_json::Value, String> {
    let client = &state.client;
    let q = quality.unwrap_or_else(|| "fast".into());
    let resp = client
        .get(format!("{}/api/3d/image-loras", SIDECAR_URL))
        .query(&[("quality_mode", q)])
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;
    let status = resp.status();
    let body = resp.text().await.unwrap_or_else(|_| "Unknown error".into());
    if !status.is_success() {
        return Err(format!("List image LoRAs failed ({}): {}", status, body));
    }
    serde_json::from_str(&body).map_err(|e| format!("Parse error: {}", e))
}

#[tauri::command]
pub async fn generate_flux_multiview_images(
    state: State<'_, SidecarState>,
    image_path: String,
    prompt: Option<String>,
    quality: Option<String>,
) -> Result<MultiviewImageResult, String> {
    let client = &state.client;
    let q = quality.unwrap_or_else(|| "fast".into());
    let resp = client
        .post(format!("{}/api/3d/generate-multiview-images", SIDECAR_URL))
        .json(&serde_json::json!({
            "image_path": image_path,
            "prompt": prompt.unwrap_or_default(),
            "quality_mode": q,
        }))
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;
    let status = resp.status();
    let body = resp.text().await.unwrap_or_else(|_| "Unknown error".into());
    if !status.is_success() {
        return Err(format!("Sidecar error ({}): {}", status, body));
    }
    serde_json::from_str(&body).map_err(|e| format!("Parse error: {} - body: {}", e, response_excerpt(&body)))
}

#[tauri::command]
pub async fn generate_wan_video(
    state: State<'_, SidecarState>,
    image_path: Option<String>,
    prompt: String,
    quality: Option<String>,
    duration_seconds: Option<i32>,
    width: Option<i32>,
    height: Option<i32>,
    standard_model: Option<String>,
    lora_acceleration: Option<bool>,
) -> Result<VideoGenerateResult, String> {
    let client = &state.client;
    let q = quality.unwrap_or_else(|| "quality".into());
    let resp = client
        .post(format!("{}/api/3d/generate-video", SIDECAR_URL))
        .json(&serde_json::json!({
            "image_path": image_path,
            "prompt": prompt,
            "quality_mode": q,
            "duration_seconds": duration_seconds.unwrap_or(4),
            "width": width.unwrap_or(1024),
            "height": height.unwrap_or(576),
            "standard_model": standard_model.unwrap_or_else(|| "5b".into()),
            "lora_acceleration": lora_acceleration.unwrap_or(false),
        }))
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;
    let status = resp.status();
    let body = resp.text().await.unwrap_or_else(|_| "Unknown error".into());
    if !status.is_success() {
        return Err(format!("Sidecar error ({}): {}", status, body));
    }
    serde_json::from_str(&body).map_err(|e| format!("Parse error: {} - body: {}", e, response_excerpt(&body)))
}

#[tauri::command]
pub async fn create_showcase_materials(
    state: State<'_, SidecarState>,
    title: String,
    prompt: String,
    model_path: Option<String>,
    image_path: Option<String>,
    scene: Option<String>,
) -> Result<ShowcaseMaterialResult, String> {
    let client = &state.client;
    let resp = client
        .post(format!("{}/api/3d/showcase-materials", SIDECAR_URL))
        .json(&serde_json::json!({
            "title": title,
            "prompt": prompt,
            "model_path": model_path,
            "image_path": image_path,
            "scene": scene,
        }))
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;
    let status = resp.status();
    let body = resp.text().await.unwrap_or_else(|_| "Unknown error".into());
    if !status.is_success() {
        return Err(format!("Sidecar error ({}): {}", status, body));
    }
    serde_json::from_str(&body).map_err(|e| format!("Parse error: {} - body: {}", e, response_excerpt(&body)))
}

#[tauri::command]
pub async fn list_generation_tasks(
    state: State<'_, SidecarState>,
    limit: Option<i32>,
) -> Result<serde_json::Value, String> {
    check_ready(&state)?;
    let client = &state.client;
    let safe_limit = limit.unwrap_or(30).clamp(1, 100);
    let resp = client
        .get(format!("{}/api/3d/tasks", SIDECAR_URL))
        .query(&[("limit", safe_limit)])
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;
    let status = resp.status();
    let body = resp.text().await.unwrap_or_else(|_| "Unknown error".into());
    if !status.is_success() {
        return Err(format!("List generation tasks failed ({}): {}", status, body));
    }
    serde_json::from_str(&body).map_err(|e| format!("Parse error: {}", e))
}

#[tauri::command]
pub async fn cancel_3d_generation(state: State<'_, SidecarState>) -> Result<bool, String> {
    let client = &state.client;
    let resp = client
        .post(format!("{}/api/3d/generate/cancel", SIDECAR_URL))
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;
    if !resp.status().is_success() {
        return Err("Cancel failed".into());
    }
    Ok(true)
}

async fn stream_3d_sse(
    app: AppHandle,
    _client: Client,
    endpoint: &str,
    body: serde_json::Value,
) {
    let client = match Client::builder()
        .connect_timeout(Duration::from_secs(10))
        .build()
    {
        Ok(client) => client,
        Err(e) => {
            let _ = app.emit("three-d-error", serde_json::json!({"message": format!("HTTP client error: {}", e)}));
            return;
        }
    };

    let resp = match client
        .post(format!("{}{}", SIDECAR_URL, endpoint))
        .json(&body)
        .send()
        .await
    {
        Ok(r) => r,
        Err(e) => {
            let _ = app.emit("three-d-error", serde_json::json!({"message": format!("Connection error: {}", e)}));
            return;
        }
    };

    if !resp.status().is_success() {
        let status_code = resp.status();
        let body_text = resp.text().await.unwrap_or_else(|_| "Unknown error".into());
        let _ = app.emit("three-d-error", serde_json::json!({"message": format!("Sidecar error ({}): {}", status_code, body_text)}));
        return;
    }

    let mut stream = resp.bytes_stream();
    let mut byte_buf: Vec<u8> = Vec::new();

    while let Some(chunk_result) = stream.next().await {
        match chunk_result {
            Ok(bytes) => {
                byte_buf.extend_from_slice(&bytes);
                while let Some(pos) = byte_buf.windows(2).position(|w| w == b"\n\n") {
                    let event_bytes = byte_buf[..pos].to_vec();
                    byte_buf.drain(..pos + 2);

                    let event_str = match String::from_utf8(event_bytes) {
                        Ok(s) => s,
                        Err(_) => continue,
                    };

                    for line in event_str.lines() {
                        if let Some(data) = line.strip_prefix("data: ") {
                            let data = data.trim();
                            if data == "[DONE]" {
                                return;
                            }
                            match serde_json::from_str::<serde_json::Value>(data) {
                                Ok(json_val) => {
                                    let event_type = json_val.get("type").and_then(|v| v.as_str()).unwrap_or("");
                                    match event_type {
                                        "progress" | "node_started" | "status" => {
                                            let _ = app.emit("three-d-progress", &json_val);
                                        }
                                        "result" => {
                                            let _ = app.emit("three-d-result", &json_val);
                                        }
                                        "error" => {
                                            let _ = app.emit("three-d-error", &json_val);
                                        }
                                        _ => {}
                                    }
                                }
                                Err(_) => {}
                            }
                        }
                    }
                }
            }
            Err(_) => {
                let _ = app.emit("three-d-error", serde_json::json!({"message": "Stream connection lost"}));
                return;
            }
        }
    }
}

#[tauri::command]
pub async fn generate_3d_text_stream(
    app: AppHandle,
    state: State<'_, SidecarState>,
    prompt: String,
    quality: Option<String>,
) -> Result<bool, String> {
    check_ready(&state)?;
    let client = state.client.clone();
    let q = quality.unwrap_or_else(|| "fast".into());

    tokio::spawn(async move {
        stream_3d_sse(
            app,
            client,
            "/api/3d/generate/text/stream",
            serde_json::json!({ "prompt": prompt, "quality_mode": q }),
        )
        .await;
    });

    Ok(true)
}

#[tauri::command]
pub async fn generate_3d_image_stream(
    app: AppHandle,
    state: State<'_, SidecarState>,
    image_path: String,
    quality: Option<String>,
) -> Result<bool, String> {
    check_ready(&state)?;
    let client = state.client.clone();
    let q = quality.unwrap_or_else(|| "fast".into());

    tokio::spawn(async move {
        stream_3d_sse(
            app,
            client,
            "/api/3d/generate/image/stream",
            serde_json::json!({ "image_path": image_path, "quality_mode": q }),
        )
        .await;
    });

    Ok(true)
}

#[tauri::command]
pub async fn generate_3d_fusion_stream(
    app: AppHandle,
    state: State<'_, SidecarState>,
    image1_path: String,
    image2_path: String,
    prompt: String,
    quality: Option<String>,
) -> Result<bool, String> {
    check_ready(&state)?;
    let client = state.client.clone();
    let q = quality.unwrap_or_else(|| "fast".into());

    tokio::spawn(async move {
        stream_3d_sse(
            app,
            client,
            "/api/3d/generate/fusion/stream",
            serde_json::json!({
                "image1_path": image1_path,
                "image2_path": image2_path,
                "prompt": prompt,
                "quality_mode": q,
            }),
        )
        .await;
    });

    Ok(true)
}

#[tauri::command]
pub async fn generate_3d_multiview_stream(
    app: AppHandle,
    state: State<'_, SidecarState>,
    image_paths: Vec<String>,
    quality: Option<String>,
) -> Result<bool, String> {
    check_ready(&state)?;
    let client = state.client.clone();
    let q = quality.unwrap_or_else(|| "fast".into());

    tokio::spawn(async move {
        stream_3d_sse(
            app,
            client,
            "/api/3d/generate/multiview/stream",
            serde_json::json!({ "image_paths": image_paths, "quality_mode": q }),
        )
        .await;
    });

    Ok(true)
}

#[tauri::command]
pub async fn get_3d_output_file(
    state: State<'_, SidecarState>,
    filename: String,
) -> Result<String, String> {
    check_ready(&state)?;
    let client = &state.client;
    let resp = client
        .get(format!("{}/api/3d/output/{}", SIDECAR_URL, filename))
        .send()
        .await
        .map_err(|e| format!("Network error: {}", e))?;
    if !resp.status().is_success() {
        return Err("File not found".into());
    }
    let bytes = resp.bytes().await.map_err(|e| e.to_string())?;
    Ok(format!("base64:{}", base64_encode(&bytes)))
}

#[tauri::command]
pub async fn export_3d_model(source_path: String, destination_path: String) -> Result<bool, String> {
    if source_path.trim().is_empty() || destination_path.trim().is_empty() {
        return Err("Source and destination paths are required".into());
    }

    fs::copy(&source_path, &destination_path)
        .map_err(|e| format!("Export failed: {}", e))?;

    Ok(true)
}

#[tauri::command]
pub async fn reveal_path(path: String) -> Result<bool, String> {
    let trimmed = path.trim();
    if trimmed.is_empty() {
        return Err("Path is required".into());
    }

    let target = Path::new(trimmed);
    let reveal_target = if target.is_file() {
        target.to_path_buf()
    } else if target.is_dir() {
        target.to_path_buf()
    } else if let Some(parent) = target.parent() {
        parent.to_path_buf()
    } else {
        return Err("Invalid path".into());
    };

    let mut command = Command::new("explorer.exe");
    if reveal_target.is_file() {
        command.arg(format!("/select,{}", reveal_target.display()));
    } else {
        command.arg(reveal_target);
    }
    command.spawn().map_err(|e| format!("Failed to open Explorer: {}", e))?;
    Ok(true)
}

fn base64_encode(data: &[u8]) -> String {
    use std::fmt::Write;
    const CHARS: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut result = String::new();
    for chunk in data.chunks(3) {
        let b0 = chunk[0] as u32;
        let b1 = if chunk.len() > 1 { chunk[1] as u32 } else { 0 };
        let b2 = if chunk.len() > 2 { chunk[2] as u32 } else { 0 };
        let n = (b0 << 16) | (b1 << 8) | b2;
        let _ = write!(result, "{}", CHARS[(n >> 18) as usize] as char);
        let _ = write!(result, "{}", CHARS[((n >> 12) & 63) as usize] as char);
        if chunk.len() > 1 {
            let _ = write!(result, "{}", CHARS[((n >> 6) & 63) as usize] as char);
        } else {
            result.push('=');
        }
        if chunk.len() > 2 {
            let _ = write!(result, "{}", CHARS[(n & 63) as usize] as char);
        } else {
            result.push('=');
        }
    }
    result
}
