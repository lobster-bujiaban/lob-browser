import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import "../styles.css";

const suggestions = ["填写并提交表单", "下载一份报表", "浏览并提取信息"];

function App() {
  const [tasks, setTasks] = useState([]);
  const [current, setCurrent] = useState(null);
  const [draft, setDraft] = useState("");
  const [newTaskOpen, setNewTaskOpen] = useState(false);
  const [running, setRunning] = useState(false);
  const [messages, setMessages] = useState([]);

  function createEmptyTask() {
    const task = { id: crypto.randomUUID(), title: "新建浏览器任务", status: "空闲", messages: [] };
    setTasks((items) => [task, ...items]);
    setCurrent(task);
    setMessages([]);
    setDraft("");
    setNewTaskOpen(false);
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
      const response = await fetch("/api/tasks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt: text }) });
      if (!response.ok) throw new Error("任务服务不可用");
      setMessages((items) => [...items, { role: "assistant", text: "任务已提交，Agent 开始观察页面并执行。" }]);
      setTasks((items) => items.map((item) => item.id === task.id ? { ...item, title: text.slice(0, 24), status: "执行中" } : item));
    } catch (error) {
      setMessages((items) => [...items, { role: "system", text: `任务提交失败：${error.message}` }]);
    } finally { setRunning(false); }
  }

  return <div className="app">
    <aside className="app-sidebar"><h1>⌁ LOB Browser</h1><button onClick={() => setNewTaskOpen(true)}>＋ 新建任务</button><h4>最近任务 <span>清空</span></h4>{tasks.map((task) => <p key={task.id} onClick={() => { setCurrent(task); setMessages(task.messages || []); }}>{task.title}<small>{task.status}</small></p>)}</aside>
    <main><header><small>BROWSER AGENT</small><h2>{current?.title || "新建浏览器任务"}</h2></header><div className="content"><section className="chat"><div className="messages">{!current && <div className="welcome"><b>让浏览器替你完成网页任务</b><em>先新建一个任务会话，再通过聊天消息启动 Agent。</em></div>}{messages.map((message, index) => <div className={`message ${message.role}`} key={index}><strong>{message.role === "user" ? "你" : "LOB Agent"}</strong><p>{message.text}</p></div>)}</div><div className="composer-area"><div className="suggestions">{suggestions.map((item) => <button key={item} onClick={() => setDraft(item)}>{item}</button>)}</div><form className="composer" onSubmit={sendMessage}><textarea value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="描述你想让浏览器完成的任务…" rows="3"/><div><span>新建任务只创建会话，发送消息后才开始执行</span><button disabled={!draft.trim() || running}>发送 ↑</button></div></form></div></section><aside className="run"><b>执行状态</b><hr/><strong>{running ? "正在执行" : current ? "等待消息" : "等待任务"}</strong><p>只有发送对话消息后，Agent 才会启动。</p></aside></div></main>
    {newTaskOpen && <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && setNewTaskOpen(false)}><div className="modal"><button className="close" onClick={() => setNewTaskOpen(false)}>×</button><small>NEW SESSION</small><h2>新建任务会话</h2><p>创建一个空白浏览器会话。此操作不会执行网页任务。</p><div className="modal-actions"><button onClick={() => setNewTaskOpen(false)}>取消</button><button className="primary" onClick={createEmptyTask}>创建任务</button></div></div></div>}
  </div>;
}

createRoot(document.getElementById("root")).render(<App />);
