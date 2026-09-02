import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "../styles.css";

const suggestions = ["填写并提交表单", "下载一份报表", "浏览并提取信息"];

function App() {
  const [tasks, setTasks] = useState([]);
  const [current, setCurrent] = useState(null);
  const [draft, setDraft] = useState("");
  const [newTaskOpen, setNewTaskOpen] = useState(false);
  const [newTaskTitle, setNewTaskTitle] = useState("");
  const [running, setRunning] = useState(false);
  const [messages, setMessages] = useState([]);

  useEffect(() => {
    fetch("/api/tasks")
      .then((response) => response.ok ? response.json() : Promise.reject(new Error("历史任务加载失败")))
      .then((items) => setTasks(items.map((item) => ({ ...item, text: item.prompt }))))
      .catch((error) => setMessages([{ role: "system", text: error.message }]));
  }, []);

  async function openTask(item) {
    setCurrent(item);
    const response = await fetch(`/api/tasks/${item.id}`);
    if (!response.ok) {
      setMessages([{ role: "system", text: "任务详情加载失败" }]);
      return;
    }
    const saved = await response.json();
    const restored = [{ role: "user", text: saved.prompt }];
    if (saved.message) restored.push({ role: saved.status === "completed" ? "assistant" : "system", text: saved.message });
    setMessages(restored);
  }

  async function removeTask(event, item) {
    event.stopPropagation();
    if (!window.confirm(`确定删除任务“${item.title}”吗？此操作不可恢复。`)) return;
    const response = await fetch(`/api/tasks/${item.id}`, { method: "DELETE" });
    if (!response.ok) return;
    setTasks((items) => items.filter((task) => task.id !== item.id));
    if (current?.id === item.id) { setCurrent(null); setMessages([]); }
  }

  async function clearTasks() {
    if (!tasks.length || !window.confirm(`确定清空全部 ${tasks.length} 条历史任务吗？此操作不可恢复。`)) return;
    const response = await fetch("/api/tasks", { method: "DELETE" });
    if (!response.ok) return;
    setTasks([]);
    setCurrent(null);
    setMessages([]);
  }

  async function followTask(id, sessionId) {
    for (;;) {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      const response = await fetch(`/api/tasks/${id}`);
      if (!response.ok) return;
      const saved = await response.json();
      setTasks((items) => items.map((item) => item.id === sessionId ? { ...item, status: saved.status } : item));
      if (["completed", "failed", "cancelled"].includes(saved.status)) {
        setMessages((items) => [...items, { role: saved.status === "completed" ? "assistant" : "system", text: saved.message || saved.status }]);
        setRunning(false);
        return;
      }
    }
  }

  async function createEmptyTask() {
    const title = newTaskTitle.trim();
    if (!title) return;
    const response = await fetch("/api/tasks/empty", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }) });
    if (!response.ok) return;
    const saved = await response.json();
    const task = { ...saved, text: "", messages: [] };
    setTasks((items) => [task, ...items]);
    setCurrent(task);
    setMessages([]);
    setDraft("");
    setNewTaskOpen(false);
    setNewTaskTitle("");
  }

  async function renameTask(event, item) {
    event.stopPropagation();
    const title = window.prompt("输入新的任务名称", item.title)?.trim();
    if (!title || title === item.title) return;
    const response = await fetch(`/api/tasks/${item.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }) });
    if (!response.ok) return;
    setTasks((items) => items.map((task) => task.id === item.id ? { ...task, title } : task));
    if (current?.id === item.id) setCurrent((task) => ({ ...task, title }));
  }

  async function sendMessage(event) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || running) return;
    const task = current || { id: crypto.randomUUID(), title: text.slice(0, 24), status: "空闲", messages: [] };
    setCurrent(task);
    setTasks((items) => items.some((item) => item.id === task.id) ? items : [task, ...items]);
    setMessages((items) => [...items, { role: "user", text }]);
    setDraft("");
    setRunning(true);
    try {
      const endpoint = current?.status === "idle" ? `/api/tasks/${current.id}/run` : "/api/tasks";
      const response = await fetch(endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt: text }) });
      if (!response.ok) throw new Error("任务服务不可用");
      const saved = await response.json();
      setMessages((items) => [...items, { role: "assistant", text: "任务已提交，正在启动浏览器 Agent。" }]);
      setTasks((items) => items.map((item) => item.id === task.id ? { ...item, status: saved.status } : item));
      await followTask(saved.id, task.id);
    } catch (error) {
      setMessages((items) => [...items, { role: "system", text: `任务提交失败：${error.message}` }]);
    }
  }

  return <div className="app">
    <aside className="app-sidebar"><h1>⌁ LOB Browser</h1><button onClick={() => { setNewTaskTitle(""); setNewTaskOpen(true); }}>＋ 新建任务</button><h4>最近任务 <button onClick={clearTasks}>清空</button></h4>{tasks.map((task) => <div className={`task-row ${current?.id === task.id ? "active" : ""}`} key={task.id} onClick={() => openTask(task)}><p>{task.title}<small>{task.status}</small></p><div className="task-actions"><button onClick={(event) => renameTask(event, task)} title="重命名">✎</button><button onClick={(event) => removeTask(event, task)} title="删除任务">×</button></div></div>)}</aside>
    <main><header><small>BROWSER AGENT</small><h2>{current?.title || "新建浏览器任务"}</h2></header><div className="content"><section className="chat"><div className="messages">{!current && <div className="welcome"><b>让浏览器替你完成网页任务</b><em>先新建一个任务会话，再通过聊天消息启动 Agent。</em></div>}{messages.map((message, index) => <div className={`message ${message.role}`} key={index}><strong>{message.role === "user" ? "你" : "LOB Agent"}</strong><p>{message.text}</p></div>)}</div><div className="composer-area"><div className="suggestions">{suggestions.map((item) => <button key={item} onClick={() => setDraft(item)}>{item}</button>)}</div><form className="composer" onSubmit={sendMessage}><textarea value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="描述你想让浏览器完成的任务…" rows="3"/><div><span>新建任务只创建会话，发送消息后才开始执行</span><button disabled={!draft.trim() || running}>发送 ↑</button></div></form></div></section><aside className="run"><b>执行状态</b><hr/><strong>{running ? "正在执行" : current ? "等待消息" : "等待任务"}</strong><p>只有发送对话消息后，Agent 才会启动。</p></aside></div></main>
    {newTaskOpen && <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && setNewTaskOpen(false)}><div className="modal"><button className="close" onClick={() => setNewTaskOpen(false)}>×</button><small>NEW SESSION</small><h2>新建任务会话</h2><p>创建一个空白浏览器会话。此操作不会执行网页任务。</p><label className="field-label">任务名称</label><input className="task-name-input" autoFocus value={newTaskTitle} onChange={(event) => setNewTaskTitle(event.target.value)} onKeyDown={(event) => event.key === "Enter" && createEmptyTask()} placeholder="例如：采集导航站网址" maxLength="80"/><div className="modal-actions"><button onClick={() => setNewTaskOpen(false)}>取消</button><button className="primary" disabled={!newTaskTitle.trim()} onClick={createEmptyTask}>创建任务</button></div></div></div>}
  </div>;
}

createRoot(document.getElementById("root")).render(<App />);
