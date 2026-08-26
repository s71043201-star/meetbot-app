/* eslint-disable */
const { useState, useEffect } = React;

const api = new Proxy({}, {
  get: (_, name) => async (...args) => {
    if (window.pywebview && window.pywebview.api) {
      return window.pywebview.api[name](...args);
    }
    throw new Error('API not ready');
  },
});

function App() {
  const [jobs, setJobs] = useState([]);
  const [sender, setSender] = useState('');
  const [appPw, setAppPw] = useState('');
  const [sending, setSending] = useState(false);

  useEffect(() => {
    (async () => {
      const d = await api.getEmailData();
      setJobs(d.jobs);
      setSender(d.sender);
    })();
  }, []);

  const toggle = (i) => {
    const next = [...jobs];
    next[i] = { ...next[i], selected: !next[i].selected };
    setJobs(next);
  };
  const setAll = (v) => setJobs(jobs.map((j) => ({ ...j, selected: v })));
  const setSendable = () => setJobs(jobs.map((j) => ({
    ...j, selected: j.status === 'pending' && !!j.to_email && j.attachments_count > 0
  })));

  const send = async () => {
    if (!appPw) {
      window.alert('請輸入 Gmail App Password');
      return;
    }
    const selected = jobs.map((j, i) => ({ i, j })).filter((x) => x.j.selected);
    if (selected.length === 0) {
      window.alert('沒有勾選任何收件人');
      return;
    }
    if (!window.confirm(`確定寄送 ${selected.length} 封信？`)) return;
    setSending(true);
    try {
      const result = await api.sendBatch(appPw, selected.map((x) => x.i));
      setJobs(result.jobs);
      window.alert(`完成！成功 ${result.sent} 封 / 失敗 ${result.failed} 封`);
    } catch (e) {
      window.alert('寄送失敗: ' + e.message);
    } finally {
      setSending(false);
    }
  };

  const counts = { pending: 0, sent: 0, failed: 0, skipped: 0 };
  jobs.forEach((j) => { counts[j.status] = (counts[j.status] || 0) + 1; });
  const selectedCount = jobs.filter((j) => j.selected).length;

  return (
    <>
      <div className="app-header">
        <div>
          <span className="app-title">📧 Gmail 寄送預覽</span>
          <span className="app-version">{sender}</span>
        </div>
        <div className="app-org">
          共 {jobs.length} 位 · 待寄 {counts.pending} · 已寄 {counts.sent} · 失敗 {counts.failed}
        </div>
      </div>

      <div style={{ padding: '16px 24px', background: '#fff',
        borderBottom: '1px solid var(--border)' }}>
        <div className="card-row" style={{ marginBottom: 12 }}>
          <button className="btn btn-ghost btn-sm" onClick={() => setAll(true)}>全選</button>
          <button className="btn btn-ghost btn-sm" onClick={() => setAll(false)}>全不選</button>
          <button className="btn btn-ghost btn-sm" onClick={setSendable}>僅選可寄送</button>
          <span style={{ flex: 1, fontSize: 12, color: 'var(--text-dim)' }}>
            已勾 {selectedCount} / {jobs.length}
          </span>
        </div>
        <div className="card-row">
          <input type="password" placeholder="Gmail App Password (16 碼)"
            value={appPw} onChange={(e) => setAppPw(e.target.value)}
            className="mono" style={{ flex: 1 }} />
          <button className="btn btn-success btn-lg"
            onClick={send} disabled={sending || !appPw}>
            {sending ? '寄送中…' : `📤 寄出 ${selectedCount} 封`}
          </button>
        </div>
      </div>

      <div style={{ padding: 24 }}>
        <table className="email-table">
          <thead>
            <tr>
              <th style={{ width: 36 }}>☑</th>
              <th>區別</th>
              <th>姓名</th>
              <th>角色</th>
              <th>診所</th>
              <th>Email</th>
              <th>附件</th>
              <th>狀態</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((j, i) => (
              <tr key={i}>
                <td><input type="checkbox" checked={!!j.selected}
                  onChange={() => toggle(i)} /></td>
                <td>{j.zone}</td>
                <td>{j.person_name}</td>
                <td>{j.role}</td>
                <td>{j.clinic_name}</td>
                <td className="mono" style={{ fontSize: 11 }}>{j.to_email}</td>
                <td>{j.attachments_count}</td>
                <td>
                  <span className={`status-pill status-${j.status}`}>
                    {j.status === 'pending' && '待寄'}
                    {j.status === 'sent' && '✓ 已寄'}
                    {j.status === 'failed' && '✕ 失敗'}
                    {j.status === 'skipped' && '略過'}
                  </span>
                  {j.error && <div style={{ fontSize: 10, color: 'var(--danger)', marginTop: 2 }}>{j.error}</div>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
