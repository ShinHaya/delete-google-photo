/**
 * Google Photos Delete Tool - Frontend JavaScript
 */

// DOM Elements
const elements = {
    // Account selector
    accountBar: document.getElementById('account-bar'),
    accountDropdown: document.getElementById('account-dropdown'),
    addAccountBtn: document.getElementById('add-account-btn'),
    removeAccountBtn: document.getElementById('remove-account-btn'),

    // Authentication
    authSection: document.getElementById('auth-section'),
    authIndicator: document.getElementById('auth-indicator'),
    authText: document.getElementById('auth-text'),
    authActions: document.getElementById('auth-actions'),
    authLoggedIn: document.getElementById('auth-logged-in'),
    loginBtn: document.getElementById('login-btn'),
    logoutBtn: document.getElementById('logout-btn'),

    // Form
    dateForm: document.getElementById('date-form'),
    startDate: document.getElementById('start-date'),
    endDate: document.getElementById('end-date'),
    dryRunBtn: document.getElementById('dry-run-btn'),
    deleteBtn: document.getElementById('delete-btn'),

    // Interrupted session
    interruptedAlert: document.getElementById('interrupted-alert'),
    interruptedInfo: document.getElementById('interrupted-info'),
    resumeBtn: document.getElementById('resume-btn'),
    cancelSessionBtn: document.getElementById('cancel-session-btn'),

    // Results
    resultsSection: document.getElementById('results-section'),
    dryRunResults: document.getElementById('dry-run-results'),
    targetCount: document.getElementById('target-count'),
    photosByDate: document.getElementById('photos-by-date'),

    // Progress
    progressSection: document.getElementById('progress-section'),
    progressFill: document.getElementById('progress-fill'),
    processedCount: document.getElementById('processed-count'),
    totalCount: document.getElementById('total-count'),
    progressPercentage: document.getElementById('progress-percentage'),
    interruptBtn: document.getElementById('interrupt-btn'),

    // Status
    statusText: document.getElementById('status-text'),
    errorMessage: document.getElementById('error-message'),

    // Modals
    confirmDialog: document.getElementById('confirm-dialog'),
    confirmMessage: document.getElementById('confirm-message'),
    confirmYes: document.getElementById('confirm-yes'),
    confirmNo: document.getElementById('confirm-no'),
    finalConfirmDialog: document.getElementById('final-confirm-dialog'),
    finalConfirmYes: document.getElementById('final-confirm-yes'),
    finalConfirmNo: document.getElementById('final-confirm-no'),
};

// State
let currentDryRunResult = null;
let currentSessionId = null;
let isProcessing = false;
let isAuthenticated = false;

// API Functions
async function apiRequest(endpoint, options = {}) {
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;

    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json',
            ...(csrfToken && { 'X-CSRF-Token': csrfToken }),
        },
    };

    const response = await fetch(endpoint, { ...defaultOptions, ...options });

    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(error.detail || `HTTP ${response.status}`);
    }

    return response.json();
}

async function performDryRun(startDate, endDate) {
    return apiRequest('/api/photos/dry-run', {
        method: 'POST',
        body: JSON.stringify({ start_date: startDate, end_date: endDate }),
    });
}

async function deletePhotos(startDate, endDate, expectedTotal) {
    return apiRequest('/api/photos/delete', {
        method: 'POST',
        body: JSON.stringify({
            start_date: startDate,
            end_date: endDate,
            confirmed: true,
            expected_total: expectedTotal,
        }),
    });
}

async function getInterruptedSession() {
    return apiRequest('/api/photos/sessions/interrupted');
}

async function resumeSession(sessionId) {
    return apiRequest(`/api/photos/sessions/${sessionId}/resume`, {
        method: 'POST',
    });
}

async function cancelSession(sessionId) {
    return apiRequest(`/api/photos/sessions/${sessionId}`, {
        method: 'DELETE',
    });
}

async function checkAuthStatus() {
    return apiRequest('/api/photos/auth/status');
}

async function performLogin() {
    return apiRequest('/api/photos/auth/login', {
        method: 'POST',
    });
}

async function performLogout() {
    return apiRequest('/api/photos/auth/logout', {
        method: 'POST',
    });
}

// Account Management Functions
let currentAccounts = [];

async function fetchAccounts() {
    try {
        const data = await apiRequest('/api/accounts');
        currentAccounts = data.accounts || [];
        renderAccountDropdown(data.accounts, data.active_account_id);
    } catch (error) {
        console.error('Failed to fetch accounts:', error);
    }
}

function renderAccountDropdown(accounts, activeId) {
    const dropdown = elements.accountDropdown;
    dropdown.innerHTML = '';

    if (accounts.length === 0) {
        elements.accountBar.style.display = 'none';
        return;
    }

    elements.accountBar.style.display = 'block';

    accounts.forEach(account => {
        const option = document.createElement('option');
        option.value = account.account_id;
        option.textContent = account.label;
        if (account.account_id === activeId) {
            option.selected = true;
        }
        dropdown.appendChild(option);
    });

    // Show remove button only when there are multiple accounts
    elements.removeAccountBtn.style.display = accounts.length > 1 ? 'inline-block' : 'none';
}

async function handleAccountSwitch() {
    const selectedId = elements.accountDropdown.value;
    if (!selectedId) return;

    try {
        setStatus('アカウントを切り替え中...');
        await apiRequest(`/api/accounts/${selectedId}/activate`, { method: 'POST' });
        await handleCheckAuth();
        setStatus('アカウントを切り替えました');
        await checkInterruptedSession();
    } catch (error) {
        setStatus(`アカウント切り替えエラー: ${error.message}`, true);
    }
}

async function handleAddAccount() {
    try {
        setStatus('新しいアカウントを作成中...');
        const account = await apiRequest('/api/accounts', { method: 'POST' });

        // Start login for the new account
        setStatus('ブラウザが開きます。Googleアカウントでログインしてください...');
        const loginResult = await apiRequest(`/api/accounts/${account.account_id}/login`, {
            method: 'POST',
        });

        if (loginResult.success) {
            setStatus('新しいアカウントでログインしました');
        } else {
            setStatus(loginResult.message || 'ログインに失敗しました', true);
        }

        // Refresh the account list
        await fetchAccounts();
        await handleCheckAuth();
    } catch (error) {
        setStatus(`アカウント追加エラー: ${error.message}`, true);
    }
}

async function handleRemoveAccount() {
    const selectedId = elements.accountDropdown.value;
    if (!selectedId) return;

    const selectedLabel = elements.accountDropdown.selectedOptions[0]?.textContent || selectedId;
    const confirmed = confirm(`アカウント「${selectedLabel}」を削除しますか？\nブラウザのセッション情報も削除されます。`);
    if (!confirmed) return;

    try {
        await apiRequest(`/api/accounts/${selectedId}`, { method: 'DELETE' });
        setStatus('アカウントを削除しました');
        await fetchAccounts();
        await handleCheckAuth();
    } catch (error) {
        setStatus(`アカウント削除エラー: ${error.message}`, true);
    }
}

// Authentication UI Functions
function updateAuthUI(authenticated) {
    isAuthenticated = authenticated;

    elements.authIndicator.classList.remove('checking', 'authenticated', 'not-authenticated');
    elements.authSection.classList.remove('authenticated', 'not-authenticated');

    if (authenticated) {
        elements.authIndicator.classList.add('authenticated');
        elements.authSection.classList.add('authenticated');
        elements.authText.textContent = '認証済み - Google Photosに接続できます';
        elements.authActions.style.display = 'none';
        elements.authLoggedIn.style.display = 'block';
        enableButtons(true);
    } else {
        elements.authIndicator.classList.add('not-authenticated');
        elements.authSection.classList.add('not-authenticated');
        elements.authText.textContent = '未認証 - 認証が必要です';
        elements.authActions.style.display = 'block';
        elements.authLoggedIn.style.display = 'none';
        enableButtons(false);
    }
}

async function handleCheckAuth() {
    // Treat "checking" as unauthenticated so that buttons are disabled and
    // the login prompt is shown while we wait for /auth/status. Otherwise,
    // after switching accounts the UI keeps showing the previous account's
    // "認証済み" state and dry-run remains clickable until the check returns.
    isAuthenticated = false;
    currentDryRunResult = null;
    elements.authIndicator.classList.remove('authenticated', 'not-authenticated');
    elements.authIndicator.classList.add('checking');
    elements.authSection.classList.remove('authenticated', 'not-authenticated');
    elements.authText.textContent = '確認中...';
    elements.authActions.style.display = 'none';
    elements.authLoggedIn.style.display = 'none';
    enableButtons(false);

    try {
        const result = await checkAuthStatus();
        updateAuthUI(result.authenticated);
    } catch (error) {
        updateAuthUI(false);
        setStatus(`認証確認エラー: ${error.message}`, true);
    }
}

async function handleLogin() {
    elements.loginBtn.disabled = true;
    elements.loginBtn.textContent = 'ログイン中...';
    setStatus('ブラウザが開きます。Googleアカウントでログインしてください...');

    try {
        const result = await performLogin();
        if (result.success) {
            // Refresh the account list so the dropdown reflects the email
            // that was actually logged in (the server updates the account
            // record via extract_account_email on success).
            await fetchAccounts();
            updateAuthUI(true);
            setStatus('ログインに成功しました');
        } else {
            setStatus(result.message || 'ログインに失敗しました', true);
        }
    } catch (error) {
        setStatus(`ログインエラー: ${error.message}`, true);
    } finally {
        elements.loginBtn.disabled = false;
        elements.loginBtn.textContent = 'Googleでログイン';
    }
}

async function handleLogout() {
    try {
        await performLogout();
        updateAuthUI(false);
        setStatus('ログアウトしました');
    } catch (error) {
        setStatus(`ログアウトエラー: ${error.message}`, true);
    }
}

// UI Functions
function setStatus(text, isError = false) {
    elements.statusText.textContent = text;
    if (isError) {
        elements.errorMessage.textContent = text;
        elements.errorMessage.style.display = 'block';
    } else {
        elements.errorMessage.style.display = 'none';
    }
}

function showSection(section, show = true) {
    section.style.display = show ? 'block' : 'none';
}

function enableButtons(enabled = true) {
    elements.dryRunBtn.disabled = !enabled;
    elements.deleteBtn.disabled = !enabled || !currentDryRunResult;
}

function updateProgress(processed, total) {
    const percentage = total > 0 ? Math.round((processed / total) * 100) : 0;
    elements.processedCount.textContent = processed;
    elements.totalCount.textContent = total;
    elements.progressPercentage.textContent = percentage;
    elements.progressFill.style.width = `${percentage}%`;
}

function showDryRunResults(result) {
    currentDryRunResult = result;
    elements.targetCount.textContent = result.total_count;

    // Show photos by date
    elements.photosByDate.innerHTML = '';
    if (result.photos_by_date && result.photos_by_date.length > 0) {
        result.photos_by_date.forEach(item => {
            const div = document.createElement('div');
            div.className = 'date-item';
            div.innerHTML = `<span>${item.date}</span><span>${item.count}枚</span>`;
            elements.photosByDate.appendChild(div);
        });
    }

    showSection(elements.dryRunResults, true);
    showSection(elements.resultsSection, true);
    elements.deleteBtn.disabled = result.total_count === 0;
}

function showConfirmDialog(message) {
    return new Promise((resolve) => {
        elements.confirmMessage.textContent = message;
        showSection(elements.confirmDialog, true);

        const handleYes = () => {
            cleanup();
            resolve(true);
        };

        const handleNo = () => {
            cleanup();
            resolve(false);
        };

        const cleanup = () => {
            showSection(elements.confirmDialog, false);
            elements.confirmYes.removeEventListener('click', handleYes);
            elements.confirmNo.removeEventListener('click', handleNo);
        };

        elements.confirmYes.addEventListener('click', handleYes);
        elements.confirmNo.addEventListener('click', handleNo);
    });
}

function showFinalConfirmDialog() {
    return new Promise((resolve) => {
        showSection(elements.finalConfirmDialog, true);

        const handleYes = () => {
            cleanup();
            resolve(true);
        };

        const handleNo = () => {
            cleanup();
            resolve(false);
        };

        const cleanup = () => {
            showSection(elements.finalConfirmDialog, false);
            elements.finalConfirmYes.removeEventListener('click', handleYes);
            elements.finalConfirmNo.removeEventListener('click', handleNo);
        };

        elements.finalConfirmYes.addEventListener('click', handleYes);
        elements.finalConfirmNo.addEventListener('click', handleNo);
    });
}

// Event Handlers
async function handleDryRun() {
    const startDate = elements.startDate.value;
    const endDate = elements.endDate.value;

    if (!startDate || !endDate) {
        setStatus('日付を入力してください', true);
        return;
    }

    try {
        enableButtons(false);
        setStatus('ドライラン実行中...');

        const result = await performDryRun(startDate, endDate);
        showDryRunResults(result);
        setStatus(`ドライラン完了: ${result.total_count}枚の写真が見つかりました`);
        enableButtons(true);
    } catch (error) {
        setStatus(`エラー: ${error.message}`, true);
        enableButtons(true);
    }
}

async function handleDelete() {
    if (!currentDryRunResult || currentDryRunResult.total_count === 0) {
        setStatus('削除する写真がありません', true);
        return;
    }

    const count = currentDryRunResult.total_count;
    const startDate = elements.startDate.value;
    const endDate = elements.endDate.value;

    // First confirmation
    const confirmed = await showConfirmDialog(
        `${count} 枚の写真をゴミ箱に移動します。よろしいですか？\n（ゴミ箱はGoogle Photos側で60日後に自動削除されます）`
    );

    if (!confirmed) {
        setStatus('キャンセルされました');
        return;
    }

    // Final confirmation
    const finalConfirmed = await showFinalConfirmDialog();

    if (!finalConfirmed) {
        setStatus('キャンセルされました');
        return;
    }

    try {
        isProcessing = true;
        enableButtons(false);
        showSection(elements.resultsSection, false);
        showSection(elements.progressSection, true);
        updateProgress(0, count);
        setStatus('削除中...');

        const result = await deletePhotos(startDate, endDate, count);

        showSection(elements.progressSection, false);
        updateProgress(result.deleted_count, count);

        // "削除できなかった" = ドライランで検出された件数 − 実際に削除された件数。
        // failed_count は明示的な削除エラーのみを数えるため、グループ化漏れ
        // などの「静かな取りこぼし」は拾えない。差分で計算する方がユーザー
        // が自力で残りを削除するときに参考になる。
        const missed = Math.max(0, count - result.deleted_count);
        if (missed > 0) {
            // isError=false: setStatus(text, true) だとステータス欄と
            // エラーメッセージ欄の両方に同じ文字列を出してしまうため、
            // 部分成功はエラー扱いせず status 欄のみに表示する。
            setStatus(
                `完了: ${result.deleted_count}枚削除、${missed}枚削除できませんでした（手動で削除してください）`
            );
        } else {
            setStatus(`完了: ${result.deleted_count}枚を削除しました`);
        }

        currentDryRunResult = null;
        enableButtons(true);
    } catch (error) {
        setStatus(`エラー: ${error.message}`, true);
        showSection(elements.progressSection, false);
        enableButtons(true);
    } finally {
        isProcessing = false;
    }
}

async function handleResume() {
    if (!currentSessionId) return;

    try {
        isProcessing = true;
        enableButtons(false);
        showSection(elements.interruptedAlert, false);
        showSection(elements.progressSection, true);
        setStatus('再開中...');

        const result = await resumeSession(currentSessionId);

        showSection(elements.progressSection, false);

        const missedResume = Math.max(
            0,
            (result.target_count || 0) - result.deleted_count
        );
        if (missedResume > 0) {
            setStatus(
                `完了: ${result.deleted_count}枚削除、${missedResume}枚削除できませんでした（手動で削除してください）`
            );
        } else {
            setStatus(`完了: ${result.deleted_count}枚を削除しました`);
        }

        currentSessionId = null;
        enableButtons(true);
    } catch (error) {
        setStatus(`エラー: ${error.message}`, true);
        showSection(elements.progressSection, false);
        enableButtons(true);
    } finally {
        isProcessing = false;
    }
}

async function handleCancelSession() {
    if (!currentSessionId) return;

    try {
        await cancelSession(currentSessionId);
        showSection(elements.interruptedAlert, false);
        currentSessionId = null;
        setStatus('セッションをキャンセルしました');
    } catch (error) {
        setStatus(`エラー: ${error.message}`, true);
    }
}

async function checkInterruptedSession() {
    try {
        const session = await getInterruptedSession();
        if (session) {
            currentSessionId = session.session_id;
            elements.interruptedInfo.textContent =
                `日付範囲: ${session.start_date} 〜 ${session.end_date}\n` +
                `進捗: ${session.processed_count} / ${session.total_count} (${session.progress_percentage.toFixed(1)}%)`;
            showSection(elements.interruptedAlert, true);
        }
    } catch (error) {
        console.error('Failed to check interrupted session:', error);
    }
}

// Initialize
function init() {
    // Set default dates (last 30 days)
    const today = new Date();
    const thirtyDaysAgo = new Date(today);
    thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);

    elements.endDate.value = today.toISOString().split('T')[0];
    elements.startDate.value = thirtyDaysAgo.toISOString().split('T')[0];

    // Attach event listeners
    elements.dryRunBtn.addEventListener('click', handleDryRun);
    elements.deleteBtn.addEventListener('click', handleDelete);
    elements.resumeBtn.addEventListener('click', handleResume);
    elements.cancelSessionBtn.addEventListener('click', handleCancelSession);
    elements.loginBtn.addEventListener('click', handleLogin);
    elements.logoutBtn.addEventListener('click', handleLogout);

    // Account management
    elements.accountDropdown.addEventListener('change', handleAccountSwitch);
    elements.addAccountBtn.addEventListener('click', handleAddAccount);
    elements.removeAccountBtn.addEventListener('click', handleRemoveAccount);

    // Load accounts, then check auth
    fetchAccounts().then(() => {
        handleCheckAuth();
        checkInterruptedSession();
    });
}

// Run on DOM ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
