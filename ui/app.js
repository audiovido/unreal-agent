const conversation = document.getElementById("conversation");
const activity = document.getElementById("activity");
const promptInput = document.getElementById("promptInput");
const sendButton = document.getElementById("sendButton");

const statusDot = document.getElementById("statusDot");
const statusText = document.getElementById("statusText");
const engineText = document.getElementById("engineText");
const editorStatus = document.getElementById("editorStatus");

const activityCount = document.getElementById("activityCount");
const sidebarActivityCount = document.getElementById("sidebarActivityCount");
const historyCount = document.getElementById("historyCount");

const runningTaskCount = document.getElementById("runningTaskCount");
const completedTaskCount = document.getElementById("completedTaskCount");
const warningTaskCount = document.getElementById("warningTaskCount");

const approvalModal = document.getElementById("approvalModal");
const approvalTitle = document.getElementById("approvalTitle");
const approvalReason = document.getElementById("approvalReason");
const approvalArgs = document.getElementById("approvalArgs");
const approveButton = document.getElementById("approveButton");
const rejectButton = document.getElementById("rejectButton");

const resetButton = document.getElementById("resetButton");
const newTaskButton = document.getElementById("newTaskButton");

const copyLastButton = document.getElementById("copyLastButton");
const clearChatButton = document.getElementById("clearChatButton");

const commandSearch = document.getElementById("commandSearch");
const commandPalette = document.getElementById("commandPalette");
const commandInput = document.getElementById("commandInput");

const notificationButton = document.getElementById("notificationButton");
const notificationPanel = document.getElementById("notificationPanel");
const closeNotificationButton = document.getElementById("closeNotificationButton");
const enableNotificationsButton = document.getElementById("enableNotificationsButton");
const notificationDot = document.getElementById("notificationDot");

const voiceButton = document.getElementById("voiceButton");
const attachButton = document.getElementById("attachButton");
const modeButton = document.getElementById("modeButton");

const currentViewName = document.getElementById("currentViewName");
const workspaceTitle = document.getElementById("workspaceTitle");

const toastRegion = document.getElementById("toastRegion");

let currentApprovalId = null;
let busy = false;
let lastEventIds = new Set();
let eventCache = [];
let lastAgentMessage = "";
let currentMode = "Agent";
let currentView = "agent";

const STORAGE_HISTORY = "unrealAgent.history.v2";
const STORAGE_NOTIFICATIONS = "unrealAgent.notifications.v1";

const VIEW_CONFIG = {
    agent: {
        label: "Agent",
        title: "Project Copilot",
        prompt: null
    },

    project: {
        label: "Project",
        title: "Project Manager",
        prompt:
            "Inspect the currently open Unreal project and give me a concise project dashboard: project name, active map, engine version if available, major systems, important folders, configuration state, warnings, and recommended next actions. Do not modify anything."
    },

    levels: {
        label: "Levels",
        title: "Level Manager",
        prompt:
            "Inspect the Unreal project's levels and current open map. Summarize available maps, active level, important actors and systems in the current level, streaming or world partition information if available, and any level-related warnings. Do not modify anything."
    },

    assets: {
        label: "Assets",
        title: "Asset Manager",
        prompt:
            "Inspect the Unreal project's assets and Content Browser structure. Summarize major asset folders, Blueprints, materials, textures, meshes, UI assets, unused or suspicious assets if detectable, and asset-related issues. Do not modify anything."
    },

    tools: {
        label: "Tools",
        title: "Unreal Tools",
        prompt:
            "Inspect which Unreal automation tools and project operations are currently available to you. Group them by inspection, levels, actors, assets, Blueprints, UI, build, debugging, and project-changing actions. Do not modify anything."
    },

    github: {
        label: "GitHub",
        title: "Source Control",
        prompt:
            "Inspect the current project's Git repository status. Report current branch, working tree state, changed files, staged files, untracked files, recent commits if available, and anything that needs attention. Do not commit, push, pull, merge, reset, checkout, rebase, or modify anything."
    },

    history: {
        label: "History",
        title: "Session History",
        prompt: null
    },

    activity: {
        label: "Activity",
        title: "Execution Monitor",
        prompt: null
    }
};

function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = String(value ?? "");
    return div.innerHTML;
}

function prettify(value) {
    if (value === null || value === undefined) {
        return "";
    }

    if (typeof value === "string") {
        return value;
    }

    try {
        return JSON.stringify(value, null, 2);
    } catch {
        return String(value);
    }
}

function showToast(message, timeout = 3200) {
    if (!toastRegion) return;

    const toast = document.createElement("div");
    toast.className = "toast";
    toast.textContent = message;

    toastRegion.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transform = "translateY(6px)";
        toast.style.transition = ".18s ease";

        setTimeout(() => toast.remove(), 220);
    }, timeout);
}

async function api(path, options = {}) {
    const response = await fetch(path, {
        headers: {
            "Content-Type": "application/json",
            ...(options.headers || {})
        },
        ...options
    });

    if (!response.ok) {
        let message = `HTTP ${response.status}`;

        try {
            const data = await response.json();
            message = data.detail || message;
        } catch {}

        throw new Error(message);
    }

    return response.json();
}

/* HISTORY */

function loadHistory() {
    try {
        return JSON.parse(localStorage.getItem(STORAGE_HISTORY) || "[]");
    } catch {
        return [];
    }
}

function saveHistoryItem(role, text) {
    const history = loadHistory();

    history.push({
        id: crypto.randomUUID
            ? crypto.randomUUID()
            : `${Date.now()}-${Math.random()}`,
        role,
        text,
        time: Date.now()
    });

    if (history.length > 200) {
        history.splice(0, history.length - 200);
    }

    localStorage.setItem(
        STORAGE_HISTORY,
        JSON.stringify(history)
    );

    updateHistoryCount();
}

function updateHistoryCount() {
    if (!historyCount) return;

    historyCount.textContent =
        String(loadHistory().length);
}

function renderHistory() {
    const history = loadHistory();

    conversation.innerHTML = "";

    const wrap = document.createElement("div");
    wrap.className = "hero-message";
    wrap.style.textAlign = "left";
    wrap.style.maxWidth = "760px";

    wrap.innerHTML = `
        <div class="hero-eyebrow">LOCAL SESSION MEMORY</div>
        <h2 style="font-size:28px;">Conversation History</h2>
        <p style="margin-left:0;">
            Messages stored locally in this browser.
        </p>
    `;

    conversation.appendChild(wrap);

    if (!history.length) {
        const empty = document.createElement("div");
        empty.className = "message agent";
        empty.textContent = "No conversation history yet.";
        conversation.appendChild(empty);
        return;
    }

    history.slice(-80).forEach(item => {
        addMessage(item.role, item.text, false);
    });
}

/* CHAT */

function removeHero() {
    const hero =
        conversation.querySelector(".hero-message");

    if (hero) {
        hero.remove();
    }
}

function addMessage(role, text, persist = true) {
    removeHero();

    const node =
        document.createElement("div");

    node.className =
        `message ${role}`;

    node.innerHTML =
        escapeHtml(text)
            .replace(/\n/g, "<br>");

    conversation.appendChild(node);

    conversation.scrollTop =
        conversation.scrollHeight;

    if (
        role === "agent" &&
        !role.includes("thinking")
    ) {
        lastAgentMessage = text;
    }

    if (
        persist &&
        !role.includes("thinking")
    ) {
        saveHistoryItem(
            role === "user" ? "user" : "agent",
            text
        );
    }

    return node;
}

function setBusy(value) {
    busy = value;

    sendButton.disabled = value;
    promptInput.disabled = value;

    if (!value) {
        promptInput.focus();
    }
}

function autoResize() {
    promptInput.style.height = "auto";

    promptInput.style.height =
        Math.min(
            promptInput.scrollHeight,
            160
        ) + "px";
}

async function handleAgentResult(
    result,
    thinkingNode = null
) {
    if (thinkingNode) {
        thinkingNode.remove();
    }

    if (
        result.state ===
        "approval_required"
    ) {
        openApproval(result);
        return;
    }

    if (result.message) {
        addMessage(
            "agent",
            result.message
        );

        fireTaskNotification(
            "Unreal Agent",
            "Task completed."
        );
    }
}

function applyMode(message) {
    if (currentMode === "Inspect") {
        return (
            "INSPECTION MODE. Do not modify, create, delete, save, rename, move, duplicate, commit, or change project content unless I explicitly approve a later action.\n\n" +
            message
        );
    }

    return message;
}

async function sendPrompt(prompt = null) {
    if (busy) return;

    let message =
        (prompt ?? promptInput.value).trim();

    if (!message) return;

    message = applyMode(message);

    promptInput.value = "";
    autoResize();

    addMessage(
        "user",
        message
    );

    const thinking =
        addMessage(
            "agent thinking",
            "Thinking…",
            false
        );

    setBusy(true);

    try {
        const result =
            await api(
                "/api/chat",
                {
                    method: "POST",
                    body: JSON.stringify({
                        message
                    })
                }
            );

        await handleAgentResult(
            result,
            thinking
        );

    } catch (error) {
        thinking.remove();

        addMessage(
            "agent",
            `Error: ${error.message}`
        );

        showToast(
            `Agent error: ${error.message}`
        );

    } finally {
        setBusy(false);

        refreshEvents();
        refreshStatus();
    }
}

/* STATUS */

async function refreshStatus() {
    try {
        const data =
            await api("/api/status");

        const unreal =
            data.unreal || {};

        if (unreal.ok) {
            statusDot.classList.add(
                "online"
            );

            statusText.textContent =
                "Unreal connected";

            engineText.textContent =
                unreal.engine
                    ? `Engine ${unreal.engine}`
                    : "Bridge online";

            if (editorStatus) {
                editorStatus.textContent =
                    "Online";
            }

        } else {
            statusDot.classList.remove(
                "online"
            );

            statusText.textContent =
                "Unreal offline";

            engineText.textContent =
                unreal.error ||
                "Bridge unavailable";

            if (editorStatus) {
                editorStatus.textContent =
                    "Offline";
            }
        }

    } catch {
        statusDot.classList.remove(
            "online"
        );

        statusText.textContent =
            "API offline";

        engineText.textContent =
            "Start the local server";

        if (editorStatus) {
            editorStatus.textContent =
                "Offline";
        }
    }
}

/* EVENTS */

function normalizeStatus(event) {
    const value =
        String(event.status || "")
            .toLowerCase();

    if (
        value.includes("success") ||
        value.includes("complete") ||
        value.includes("done")
    ) {
        return "success";
    }

    if (
        value.includes("error") ||
        value.includes("fail")
    ) {
        return "error";
    }

    if (
        value.includes("warning") ||
        value.includes("approval")
    ) {
        return "warning";
    }

    return value || "running";
}

function renderEvent(event) {
    if (lastEventIds.has(event.id)) {
        return;
    }

    lastEventIds.add(event.id);

    const empty =
        activity.querySelector(
            ".empty-activity"
        );

    if (empty) {
        empty.remove();
    }

    const status =
        normalizeStatus(event);

    const node =
        document.createElement("div");

    node.className =
        `activity-item ${status}`;

    node.dataset.status = status;

    node.innerHTML = `
        <div class="activity-top">
            <span class="activity-indicator"></span>

            <div class="activity-title">
                ${escapeHtml(event.title || "Agent task")}
            </div>
        </div>

        ${
            event.detail
                ? `
                    <div class="activity-detail">
                        ${escapeHtml(
                            prettify(event.detail)
                        )}
                    </div>
                  `
                : ""
        }
    `;

    activity.appendChild(node);

    activity.scrollTop =
        activity.scrollHeight;

    if (status === "success") {
        fireTaskNotification(
            "Unreal task complete",
            event.title || "Task completed."
        );
    }

    if (status === "error") {
        fireTaskNotification(
            "Unreal task failed",
            event.title || "A task failed."
        );
    }
}

function updateTaskCounters(events) {
    let running = 0;
    let completed = 0;
    let warning = 0;

    events.forEach(event => {
        const status =
            normalizeStatus(event);

        if (status === "success") {
            completed++;
        } else if (
            status === "warning" ||
            status === "error"
        ) {
            warning++;
        } else {
            running++;
        }
    });

    activityCount.textContent =
        String(events.length);

    if (sidebarActivityCount) {
        sidebarActivityCount.textContent =
            String(events.length);
    }

    if (runningTaskCount) {
        runningTaskCount.textContent =
            String(running);
    }

    if (completedTaskCount) {
        completedTaskCount.textContent =
            String(completed);
    }

    if (warningTaskCount) {
        warningTaskCount.textContent =
            String(warning);
    }
}

async function refreshEvents() {
    try {
        const data =
            await api("/api/events");

        const events =
            data.events || [];

        eventCache = events;

        events.forEach(renderEvent);

        updateTaskCounters(events);

    } catch {}
}

/* APPROVAL */

function openApproval(result) {
    currentApprovalId =
        result.approval_id;

    approvalTitle.textContent =
        result.tool ||
        "Allow this action?";

    approvalReason.textContent =
        result.reason ||
        "This operation changes the Unreal project.";

    approvalArgs.textContent =
        prettify(result.args);

    approvalModal.classList.remove(
        "hidden"
    );
}

function closeApproval() {
    currentApprovalId = null;

    approvalModal.classList.add(
        "hidden"
    );
}

async function respondApproval(approved) {
    if (!currentApprovalId) {
        return;
    }

    const approvalId =
        currentApprovalId;

    closeApproval();

    const thinking =
        addMessage(
            "agent thinking",
            approved
                ? "Executing approved action…"
                : "Cancelling action…",
            false
        );

    setBusy(true);

    try {
        const result =
            await api(
                "/api/approval",
                {
                    method: "POST",
                    body: JSON.stringify({
                        approval_id:
                            approvalId,
                        approved
                    })
                }
            );

        await handleAgentResult(
            result,
            thinking
        );

    } catch (error) {
        thinking.remove();

        addMessage(
            "agent",
            `Error: ${error.message}`
        );

    } finally {
        setBusy(false);

        refreshEvents();
        refreshStatus();
    }
}

/* NOTIFICATIONS */

function notificationsSupported() {
    return (
        "Notification" in window
    );
}

function updateNotificationUI() {
    if (!notificationsSupported()) {
        return;
    }

    if (
        Notification.permission ===
        "granted"
    ) {
        notificationDot?.classList.add(
            "hidden"
        );

        localStorage.setItem(
            STORAGE_NOTIFICATIONS,
            "granted"
        );
    } else {
        notificationDot?.classList.remove(
            "hidden"
        );
    }
}

async function requestNotifications() {
    if (!notificationsSupported()) {
        showToast(
            "Desktop notifications are not supported in this browser."
        );

        return;
    }

    try {
        const permission =
            await Notification.requestPermission();

        updateNotificationUI();

        if (permission === "granted") {
            showToast(
                "Desktop notifications enabled."
            );

            new Notification(
                "Unreal Agent",
                {
                    body:
                        "Notifications are ready."
                }
            );
        } else {
            showToast(
                "Notification permission was not granted."
            );
        }

    } catch {
        showToast(
            "Could not request notification permission."
        );
    }
}

function fireTaskNotification(
    title,
    body
) {
    if (
        notificationsSupported() &&
        Notification.permission ===
        "granted" &&
        document.hidden
    ) {
        try {
            new Notification(
                title,
                { body }
            );
        } catch {}
    }
}

/* NAVIGATION */

function setActiveView(view) {
    const config =
        VIEW_CONFIG[view];

    if (!config) return;

    currentView = view;

    document
        .querySelectorAll(".nav-item")
        .forEach(item => {
            item.classList.toggle(
                "active",
                item.dataset.view === view
            );
        });

    if (currentViewName) {
        currentViewName.textContent =
            config.label;
    }

    if (workspaceTitle) {
        workspaceTitle.textContent =
            config.title;
    }

    if (view === "history") {
        renderHistory();
        return;
    }

    if (view === "activity") {
        document
            .querySelector(".activity-panel")
            ?.scrollIntoView({
                behavior: "smooth",
                block: "nearest"
            });

        return;
    }

    if (
        config.prompt &&
        !busy
    ) {
        sendPrompt(config.prompt);
    }
}

/* COMMAND PALETTE */

function openCommandPalette() {
    commandPalette.classList.remove(
        "hidden"
    );

    setTimeout(() => {
        commandInput?.focus();
    }, 40);
}

function closeCommandPalette() {
    commandPalette.classList.add(
        "hidden"
    );

    if (commandInput) {
        commandInput.value = "";
    }
}

function filterCommands() {
    const query =
        commandInput.value
            .toLowerCase()
            .trim();

    document
        .querySelectorAll(
            ".command-item"
        )
        .forEach(item => {
            const text =
                item.textContent
                    .toLowerCase();

            item.style.display =
                text.includes(query)
                    ? ""
                    : "none";
        });
}

/* COPY */

async function copyLastResponse() {
    if (!lastAgentMessage) {
        showToast(
            "No agent response to copy yet."
        );

        return;
    }

    try {
        await navigator.clipboard.writeText(
            lastAgentMessage
        );

        showToast(
            "Last response copied."
        );

    } catch {
        showToast(
            "Could not access clipboard."
        );
    }
}

/* VOICE */

function setupVoiceInput() {
    const SpeechRecognition =
        window.SpeechRecognition ||
        window.webkitSpeechRecognition;

    if (!SpeechRecognition) {
        voiceButton?.addEventListener(
            "click",
            () => {
                showToast(
                    "Voice recognition is not available in this browser."
                );
            }
        );

        return;
    }

    const recognition =
        new SpeechRecognition();

    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = "fa-IR";

    let baseText = "";

    voiceButton?.addEventListener(
        "click",
        () => {
            try {
                baseText =
                    promptInput.value.trim();

                recognition.start();

                voiceButton.style.color =
                    "#8bb2ff";

                showToast(
                    "Listening… Speak in Persian or English."
                );

            } catch {}
        }
    );

    recognition.onresult =
        event => {
            let transcript = "";

            for (
                let i = event.resultIndex;
                i < event.results.length;
                i++
            ) {
                transcript +=
                    event.results[i][0]
                        .transcript;
            }

            promptInput.value =
                (
                    baseText +
                    (baseText ? " " : "") +
                    transcript
                ).trim();

            autoResize();
        };

    recognition.onend =
        () => {
            voiceButton.style.color = "";
            promptInput.focus();
        };

    recognition.onerror =
        () => {
            voiceButton.style.color = "";

            showToast(
                "Voice recognition stopped."
            );
        };
}

/* ATTACHMENT */

function setupAttachmentButton() {
    const input =
        document.createElement("input");

    input.type = "file";
    input.multiple = true;
    input.style.display = "none";

    document.body.appendChild(input);

    attachButton?.addEventListener(
        "click",
        () => input.click()
    );

    input.addEventListener(
        "change",
        () => {
            const files =
                Array.from(input.files || []);

            if (!files.length) return;

            const names =
                files
                    .map(file => file.name)
                    .join(", ");

            promptInput.value =
                (
                    promptInput.value +
                    `${
                        promptInput.value
                            ? "\n"
                            : ""
                    }Attached local files: ${names}`
                );

            autoResize();

            showToast(
                `${files.length} file${files.length > 1 ? "s" : ""} selected. File names added as context.`
            );

            input.value = "";
        }
    );
}

/* MODE */

function cycleMode() {
    currentMode =
        currentMode === "Agent"
            ? "Inspect"
            : "Agent";

    if (modeButton) {
        modeButton.childNodes.forEach(
            node => {
                if (
                    node.nodeType ===
                    Node.TEXT_NODE
                ) {
                    node.textContent =
                        ` ${currentMode} `;
                }
            }
        );
    }

    showToast(
        currentMode === "Inspect"
            ? "Inspect mode: read-only instructions preferred."
            : "Agent mode enabled."
    );
}

/* FILTERS */

function filterActivity(filter) {
    document
        .querySelectorAll(
            ".activity-tab"
        )
        .forEach(button => {
            button.classList.toggle(
                "active",
                button.dataset.activityFilter ===
                    filter
            );
        });

    document
        .querySelectorAll(
            ".activity-item"
        )
        .forEach(item => {
            const status =
                item.dataset.status || "";

            let visible = true;

            if (filter === "running") {
                visible =
                    status !== "success" &&
                    status !== "error" &&
                    status !== "warning";
            }

            if (filter === "completed") {
                visible =
                    status === "success";
            }

            item.style.display =
                visible ? "" : "none";
        });
}

/* RESET */

async function resetSession() {
    try {
        await api(
            "/api/reset",
            {
                method: "POST"
            }
        );

        location.reload();

    } catch (error) {
        showToast(
            `Reset failed: ${error.message}`
        );
    }
}

function clearConversationOnly() {
    conversation.innerHTML = "";

    const message =
        document.createElement("div");

    message.className =
        "message agent";

    message.textContent =
        "Conversation cleared locally. Start a new task whenever you're ready.";

    conversation.appendChild(message);

    showToast(
        "Conversation view cleared."
    );
}

/* EVENTS */

promptInput.addEventListener(
    "input",
    autoResize
);

promptInput.addEventListener(
    "keydown",
    event => {
        if (
            event.key === "Enter" &&
            !event.shiftKey
        ) {
            event.preventDefault();
            sendPrompt();
        }
    }
);

sendButton.addEventListener(
    "click",
    () => sendPrompt()
);

approveButton.addEventListener(
    "click",
    () => respondApproval(true)
);

rejectButton.addEventListener(
    "click",
    () => respondApproval(false)
);

resetButton?.addEventListener(
    "click",
    resetSession
);

newTaskButton?.addEventListener(
    "click",
    () => {
        setActiveView("agent");
        promptInput.focus();
        showToast(
            "Ready for a new task."
        );
    }
);

copyLastButton?.addEventListener(
    "click",
    copyLastResponse
);

clearChatButton?.addEventListener(
    "click",
    clearConversationOnly
);

commandSearch?.addEventListener(
    "click",
    openCommandPalette
);

commandInput?.addEventListener(
    "input",
    filterCommands
);

commandPalette?.addEventListener(
    "click",
    event => {
        if (
            event.target ===
            commandPalette
        ) {
            closeCommandPalette();
        }
    }
);

document
    .querySelectorAll(
        ".command-item"
    )
    .forEach(item => {
        item.addEventListener(
            "click",
            () => {
                const prompt =
                    item.dataset.commandPrompt;

                closeCommandPalette();

                if (prompt) {
                    sendPrompt(prompt);
                }
            }
        );
    });

document
    .querySelectorAll(
        ".quick-action"
    )
    .forEach(button => {
        button.addEventListener(
            "click",
            () => {
                sendPrompt(
                    button.dataset.prompt
                );
            }
        );
    });

document
    .querySelectorAll(
        ".nav-item"
    )
    .forEach(button => {
        button.addEventListener(
            "click",
            () => {
                setActiveView(
                    button.dataset.view
                );
            }
        );
    });

document
    .querySelectorAll(
        ".activity-tab"
    )
    .forEach(button => {
        button.addEventListener(
            "click",
            () => {
                filterActivity(
                    button.dataset.activityFilter
                );
            }
        );
    });

notificationButton?.addEventListener(
    "click",
    () => {
        notificationPanel
            ?.classList
            .toggle("hidden");
    }
);

closeNotificationButton
    ?.addEventListener(
        "click",
        () => {
            notificationPanel
                ?.classList
                .add("hidden");
        }
    );

enableNotificationsButton
    ?.addEventListener(
        "click",
        requestNotifications
    );

modeButton?.addEventListener(
    "click",
    cycleMode
);

document.addEventListener(
    "keydown",
    event => {
        const commandShortcut =
            (event.ctrlKey || event.metaKey) &&
            event.key.toLowerCase() === "k";

        if (commandShortcut) {
            event.preventDefault();
            openCommandPalette();
        }

        if (
            event.key === "Escape"
        ) {
            closeCommandPalette();

            notificationPanel
                ?.classList
                .add("hidden");

            if (
                approvalModal &&
                !approvalModal
                    .classList
                    .contains("hidden")
            ) {
                closeApproval();
            }
        }
    }
);


function startLiveActivityStream() {
    if (!("EventSource" in window)) {
        return;
    }

    const source = new EventSource("/api/events/stream");

    source.onmessage = event => {
        try {
            const item = JSON.parse(event.data);

            eventCache.push(item);

            if (eventCache.length > 300) {
                eventCache = eventCache.slice(-300);
            }

            renderEvent(item);
            updateTaskCounters(eventCache);
        } catch {}
    };

    source.onerror = () => {
        source.close();

        setTimeout(
            startLiveActivityStream,
            2000
        );
    };
}

/* STARTUP */

setupVoiceInput();
setupAttachmentButton();

updateHistoryCount();
updateNotificationUI();

refreshStatus();
refreshEvents();
startLiveActivityStream();

setInterval(
    refreshStatus,
    15000
);

setInterval(
    refreshEvents,
    5000
);

promptInput.focus();
