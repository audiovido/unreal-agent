const conversation =
    document.getElementById("conversation");

const activity =
    document.getElementById("activity");

const promptInput =
    document.getElementById("promptInput");

const sendButton =
    document.getElementById("sendButton");

const statusDot =
    document.getElementById("statusDot");

const statusText =
    document.getElementById("statusText");

const engineText =
    document.getElementById("engineText");

const activityCount =
    document.getElementById("activityCount");

const approvalModal =
    document.getElementById("approvalModal");

const approvalTitle =
    document.getElementById("approvalTitle");

const approvalReason =
    document.getElementById("approvalReason");

const approvalArgs =
    document.getElementById("approvalArgs");

const approveButton =
    document.getElementById("approveButton");

const rejectButton =
    document.getElementById("rejectButton");

const resetButton =
    document.getElementById("resetButton");


let currentApprovalId = null;

let busy = false;

let lastEventIds = new Set();


function escapeHtml(text) {
    const div =
        document.createElement("div");

    div.textContent =
        String(text ?? "");

    return div.innerHTML;
}


function prettify(value) {
    if (
        value === null ||
        value === undefined
    ) {
        return "";
    }

    if (
        typeof value === "string"
    ) {
        return value;
    }

    try {
        return JSON.stringify(
            value,
            null,
            2
        );
    } catch {
        return String(value);
    }
}


function addMessage(role, text) {
    const hero =
        conversation.querySelector(
            ".hero-message"
        );

    if (hero) {
        hero.remove();
    }

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
            180
        ) + "px";
}


async function api(
    path,
    options = {}
) {
    const response =
        await fetch(path, {
            headers: {
                "Content-Type":
                    "application/json",
                ...(options.headers || {})
            },
            ...options
        });

    if (!response.ok) {
        let message =
            `HTTP ${response.status}`;

        try {
            const data =
                await response.json();

            message =
                data.detail || message;
        } catch {}

        throw new Error(message);
    }

    return response.json();
}


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
        } else {
            statusDot.classList.remove(
                "online"
            );

            statusText.textContent =
                "Unreal offline";

            engineText.textContent =
                unreal.error || "Bridge unavailable";
        }
    } catch {
        statusDot.classList.remove(
            "online"
        );

        statusText.textContent =
            "API offline";

        engineText.textContent =
            "Start the local server";
    }
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

    const node =
        document.createElement("div");

    node.className =
        `activity-item ${event.status || ""}`;

    node.innerHTML = `
        <div class="activity-top">
            <span class="activity-indicator"></span>
            <div class="activity-title">
                ${escapeHtml(event.title)}
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
}


async function refreshEvents() {
    try {
        const data =
            await api("/api/events");

        const events =
            data.events || [];

        events.forEach(renderEvent);

        activityCount.textContent =
            String(events.length);
    } catch {}
}


function openApproval(result) {
    currentApprovalId =
        result.approval_id;

    approvalTitle.textContent =
        result.tool;

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

    if (
        result.message
    ) {
        addMessage(
            "agent",
            result.message
        );
    }
}


async function sendPrompt(
    prompt = null
) {
    if (busy) {
        return;
    }

    const message =
        (prompt ?? promptInput.value)
        .trim();

    if (!message) {
        return;
    }

    promptInput.value = "";
    autoResize();

    addMessage(
        "user",
        message
    );

    const thinking =
        addMessage(
            "agent thinking",
            "Thinking…"
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

    } finally {
        setBusy(false);

        refreshEvents();
        refreshStatus();
    }
}


async function respondApproval(
    approved
) {
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
                : "Cancelling action…"
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


resetButton.addEventListener(
    "click",
    async () => {
        await api(
            "/api/reset",
            {
                method: "POST"
            }
        );

        location.reload();
    }
);


document
    .querySelectorAll(".suggestion")
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


refreshStatus();
refreshEvents();

setInterval(refreshStatus, 15000);

setInterval(refreshEvents, 5000);

promptInput.focus();

