(() => {
    "use strict";

    const state = { csrf: "", candidates: new Map() };
    const byId = (id) => document.getElementById(id);

    function showNotice(message, isError = false) {
        const notice = byId("notice");
        notice.textContent = message;
        notice.classList.toggle("error-notice", isError);
        notice.hidden = false;
        window.clearTimeout(showNotice.timer);
        showNotice.timer = window.setTimeout(() => { notice.hidden = true; }, 4500);
    }

    async function api(path, options = {}) {
        const headers = { Accept: "application/json", ...(options.headers || {}) };
        if (options.body) headers["Content-Type"] = "application/json";
        if (options.method && options.method !== "GET") headers["X-CSRF-Token"] = state.csrf;
        const response = await fetch(path, { credentials: "same-origin", ...options, headers });
        let payload = {};
        try { payload = await response.json(); } catch (_) { payload = {}; }
        if (response.status === 401) {
            showLogin(true);
            throw new Error("Phiên quản trị đã hết hạn.");
        }
        if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
        return payload;
    }

    function showLogin(show, configured = true) {
        byId("login-view").hidden = !show;
        byId("admin-view").hidden = show;
        if (show && !configured) {
            byId("login-help").textContent = "Chưa cấu hình ADMIN_AUTH_USER, ADMIN_AUTH_PASSWORD và ADMIN_SESSION_SECRET trên máy chủ.";
            byId("login-form").hidden = true;
        }
    }

    function cell(text, className = "") {
        const td = document.createElement("td");
        td.textContent = text ?? "—";
        if (className) td.className = className;
        return td;
    }

    function badge(text) {
        const value = document.createElement("span");
        value.className = "badge";
        value.textContent = text || "—";
        return value;
    }

    function actionButton(label, handler, className = "secondary") {
        const button = document.createElement("button");
        button.type = "button";
        button.className = className;
        button.textContent = label;
        button.addEventListener("click", handler);
        return button;
    }

    function formatDate(value) {
        if (!value) return "—";
        const date = new Date(value);
        return Number.isNaN(date.valueOf()) ? value : date.toLocaleString("vi-VN");
    }

    function resultLabel(item) {
        if (item.success) return `Thành công · ${item.rows_returned ?? 0} dòng`;
        return item.error ? `Lỗi · ${item.error}` : "Lỗi";
    }

    async function loadReports() {
        const data = await api("/api/admin/reports?limit=100");
        const summary = data.summary;
        const metrics = [
            ["Yêu cầu", summary.total_requests],
            ["Thành công", `${summary.success_rate_percent ?? 0}%`],
            ["P95", `${summary.p95_duration_ms ?? 0} ms`],
            ["Đã đánh giá", summary.reviewed_requests],
            ["Tỷ lệ duyệt", `${summary.approval_rate_percent ?? 0}%`],
        ];
        const cards = byId("summary-cards");
        cards.replaceChildren();
        metrics.forEach(([label, value]) => {
            const card = document.createElement("div");
            card.className = "metric";
            const labelNode = document.createElement("span");
            labelNode.textContent = label;
            const strong = document.createElement("strong");
            strong.textContent = value;
            card.append(labelNode, strong);
            cards.append(card);
        });

        const body = byId("reports-body");
        body.replaceChildren();
        data.items.forEach((item) => {
            const row = document.createElement("tr");
            row.append(cell(formatDate(item.timestamp)), cell(item.question, "question-cell"));
            const result = cell(resultLabel(item), item.success ? "status-success" : "status-failed");
            row.append(result, cell(item.feedback || "Chưa có"));
            const training = document.createElement("td");
            training.append(badge(item.training?.status || (item.generated_sql ? "pending" : "Không có SQL")));
            row.append(training);
            const actions = document.createElement("td");
            if (item.training?.id) actions.append(actionButton("Duyệt", () => openCandidate(item.training.id)));
            row.append(actions);
            body.append(row);
        });
    }

    async function loadCandidates() {
        const filter = byId("candidate-status").value;
        const query = filter ? `?status=${encodeURIComponent(filter)}` : "";
        const data = await api(`/api/admin/training/candidates${query}`);
        state.candidates.clear();
        const body = byId("candidates-body");
        body.replaceChildren();
        data.items.forEach((item) => {
            state.candidates.set(item.id, item);
            const row = document.createElement("tr");
            row.append(cell(formatDate(item.updated_at)), cell(item.question, "question-cell"), cell(item.feedback || "Chưa có"), cell(item.test_status || "Chưa kiểm tra"));
            const statusCell = document.createElement("td");
            statusCell.append(badge(item.status));
            row.append(statusCell);
            const actions = document.createElement("td");
            actions.append(actionButton("Mở", () => openCandidate(item.id)));
            row.append(actions);
            body.append(row);
        });
    }

    async function openCandidate(candidateId) {
        let item = state.candidates.get(candidateId);
        if (!item) item = await api(`/api/admin/training/candidates/${candidateId}`);
        byId("review-id").value = item.id;
        byId("review-question").value = item.question;
        byId("review-sql").value = item.corrected_sql || item.generated_sql;
        byId("review-notes").value = item.reviewer_notes || "";
        byId("review-meta").textContent = `Trạng thái: ${item.status} · Phản hồi: ${item.feedback || "chưa có"} · Kiểm tra: ${item.test_status || "chưa chạy"}`;
        byId("preview-result").hidden = true;
        const locked = item.status === "approved" || item.status === "rejected";
        byId("approve-button").disabled = locked;
        byId("reject-button").disabled = locked;
        byId("candidate-dialog").showModal();
    }

    async function reviewAction(action) {
        const id = byId("review-id").value;
        const sql = byId("review-sql").value;
        const notes = byId("review-notes").value;
        const button = action === "preview" ? byId("preview-button") : byId("approve-button");
        button.disabled = true;
        try {
            const data = await api(`/api/admin/training/candidates/${id}/${action}`, { method: "POST", body: JSON.stringify({ sql, notes }) });
            const preview = action === "approve" ? data.preview : data;
            byId("preview-result").textContent = JSON.stringify(preview, null, 2);
            byId("preview-result").hidden = false;
            if (action === "approve") {
                showNotice("Đã kiểm tra và đồng bộ mẫu vào Chroma.");
                await Promise.all([loadCandidates(), loadMemories(), loadReports()]);
                byId("candidate-dialog").close();
            }
        } catch (error) { showNotice(error.message, true); }
        finally { button.disabled = false; }
    }

    async function rejectCurrent() {
        const id = byId("review-id").value;
        try {
            await api(`/api/admin/training/candidates/${id}/reject`, { method: "POST", body: JSON.stringify({ notes: byId("review-notes").value }) });
            byId("candidate-dialog").close();
            showNotice("Đã từ chối ứng viên huấn luyện.");
            await Promise.all([loadCandidates(), loadReports()]);
        } catch (error) { showNotice(error.message, true); }
    }

    async function loadMemories() {
        const data = await api("/api/admin/training/memories");
        const body = byId("memories-body");
        body.replaceChildren();
        data.items.forEach((item) => {
            const row = document.createElement("tr");
            const content = item.memory_type === "tool" ? `${item.question}\n${item.sql}` : item.content;
            row.append(cell(formatDate(item.updated_at)), cell(item.memory_type), cell(item.source_type), cell(content, "sql-snippet"));
            const statusCell = document.createElement("td");
            statusCell.append(badge(item.status));
            row.append(statusCell);
            const actions = document.createElement("td");
            if (item.status === "active") actions.append(actionButton("Vô hiệu hóa", () => disableMemory(item.id), "danger"));
            if (item.status === "disabled" || item.status === "sync_failed") actions.append(actionButton("Kích hoạt", () => enableMemory(item.id), "secondary"));
            row.append(actions);
            body.append(row);
        });
    }

    async function disableMemory(id) {
        if (!window.confirm("Vô hiệu hóa bộ nhớ này và xóa khỏi Chroma?")) return;
        try {
            await api(`/api/admin/training/memories/${encodeURIComponent(id)}/disable`, { method: "POST", body: "{}" });
            showNotice("Đã vô hiệu hóa bộ nhớ.");
            await loadMemories();
        } catch (error) { showNotice(error.message, true); }
    }

    async function enableMemory(id) {
        try {
            await api(`/api/admin/training/memories/${encodeURIComponent(id)}/enable`, { method: "POST", body: "{}" });
            showNotice("Đã đồng bộ và kích hoạt lại bộ nhớ.");
            await loadMemories();
        } catch (error) { showNotice(error.message, true); }
    }

    async function loadAudit() {
        const data = await api("/api/admin/training/audit");
        const body = byId("audit-body");
        body.replaceChildren();
        data.items.forEach((item) => {
            const row = document.createElement("tr");
            row.append(cell(formatDate(item.created_at)), cell(item.actor), cell(item.action), cell(`${item.entity_type}: ${item.entity_id}`));
            body.append(row);
        });
    }

    async function loadTab(name) {
        if (name === "reports") await loadReports();
        if (name === "training") await loadCandidates();
        if (name === "memories") await loadMemories();
        if (name === "audit") await loadAudit();
    }

    document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", async () => {
        document.querySelectorAll(".tab").forEach((item) => item.classList.toggle("active", item === tab));
        document.querySelectorAll(".tab-panel").forEach((panel) => { panel.hidden = panel.id !== `tab-${tab.dataset.tab}`; });
        try { await loadTab(tab.dataset.tab); } catch (error) { showNotice(error.message, true); }
    }));

    byId("login-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        byId("login-error").textContent = "";
        try {
            const data = await api("/api/admin/login", { method: "POST", body: JSON.stringify({ username: byId("login-username").value, password: byId("login-password").value }) });
            state.csrf = data.csrf_token;
            byId("admin-user").textContent = data.username;
            byId("login-password").value = "";
            showLogin(false);
            await loadReports();
        } catch (error) { byId("login-error").textContent = error.message; }
    });

    byId("logout-button").addEventListener("click", async () => {
        try { await api("/api/admin/logout", { method: "POST", body: "{}" }); } finally { state.csrf = ""; showLogin(true); }
    });
    byId("refresh-reports").addEventListener("click", () => loadReports().catch((error) => showNotice(error.message, true)));
    byId("refresh-candidates").addEventListener("click", () => loadCandidates().catch((error) => showNotice(error.message, true)));
    byId("candidate-status").addEventListener("change", () => loadCandidates().catch((error) => showNotice(error.message, true)));
    byId("refresh-memories").addEventListener("click", () => loadMemories().catch((error) => showNotice(error.message, true)));
    byId("refresh-audit").addEventListener("click", () => loadAudit().catch((error) => showNotice(error.message, true)));
    byId("preview-button").addEventListener("click", () => reviewAction("preview"));
    byId("approve-button").addEventListener("click", () => reviewAction("approve"));
    byId("reject-button").addEventListener("click", rejectCurrent);

    byId("manual-candidate-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
            await api("/api/admin/training/candidates", { method: "POST", body: JSON.stringify({ question: byId("manual-question").value, sql: byId("manual-sql").value, notes: byId("manual-notes").value }) });
            event.target.reset();
            showNotice("Đã thêm ứng viên vào hàng chờ.");
            await loadCandidates();
        } catch (error) { showNotice(error.message, true); }
    });

    byId("text-memory-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
            await api("/api/admin/training/memories/text", { method: "POST", body: JSON.stringify({ content: byId("text-memory-content").value }) });
            event.target.reset();
            showNotice("Đã lưu ghi chú nghiệp vụ vào Chroma.");
            await loadMemories();
        } catch (error) { showNotice(error.message, true); }
    });

    (async () => {
        try {
            const session = await api("/api/admin/session");
            if (!session.authenticated) { showLogin(true, session.configured); return; }
            state.csrf = session.csrf_token;
            byId("admin-user").textContent = session.username;
            showLogin(false);
            await loadReports();
        } catch (error) { showLogin(true); byId("login-error").textContent = error.message; }
    })();
})();
