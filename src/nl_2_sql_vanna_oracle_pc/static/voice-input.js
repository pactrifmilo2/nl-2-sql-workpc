/**
 * Voice-to-text for vanna-chat (Web Speech API).
 * Injects a microphone button into the chat shadow DOM.
 */
(function () {
  const config = window.VOICE_INPUT_CONFIG || {};
  const lang = config.lang || "vi-VN";
  const continuous = config.continuous ?? false;

  const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;

  function getVannaChat() {
    return document.querySelector("vanna-chat");
  }

  function getMessageInput(vannaChat) {
    return vannaChat?.shadowRoot?.querySelector("textarea.message-input");
  }

  function getInputContainer(vannaChat) {
    return vannaChat?.shadowRoot?.querySelector(".chat-input-container");
  }

  function injectStyles(vannaChat) {
    const root = vannaChat.shadowRoot;
    if (!root || root.querySelector("#voice-input-styles")) {
      return;
    }

    const style = document.createElement("style");
    style.id = "voice-input-styles";
    style.textContent = `
      .chat-input-container {
        gap: 0.5rem;
      }

      .voice-input-button {
        flex-shrink: 0;
        width: 2.5rem;
        height: 2.5rem;
        border: 1px solid var(--vanna-outline-default, #cbd5e1);
        border-radius: var(--vanna-border-radius-lg, 0.5rem);
        background: var(--vanna-background-default, #fff);
        color: var(--vanna-accent-primary-default, #15a8a8);
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease;
      }

      .voice-input-button:hover:not(:disabled) {
        background: var(--vanna-accent-primary-subtle, #e6f7f7);
        border-color: var(--vanna-accent-primary-default, #15a8a8);
      }

      .voice-input-button:disabled {
        opacity: 0.45;
        cursor: not-allowed;
      }

      .voice-input-button.is-listening {
        color: #fff;
        background: #dc2626;
        border-color: #dc2626;
        animation: voice-input-pulse 1.2s ease-in-out infinite;
      }

      @keyframes voice-input-pulse {
        0%, 100% { box-shadow: 0 0 0 0 rgba(220, 38, 38, 0.45); }
        50% { box-shadow: 0 0 0 8px rgba(220, 38, 38, 0); }
      }

      .voice-input-hint {
        font-size: 0.75rem;
        color: var(--vanna-foreground-muted, #64748b);
        padding: 0.25rem 0.5rem 0;
        min-height: 1.25rem;
      }
    `;
    root.appendChild(style);
  }

  function micIcon(listening) {
    if (listening) {
      return `<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <rect x="6" y="6" width="12" height="12" rx="2"></rect>
      </svg>`;
    }
    return `<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M12 14a3 3 0 0 0 3-3V5a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 14 0h-2zm-5 7a7 7 0 0 0 7-7h-2a5 5 0 0 1-10 0H5a7 7 0 0 0 7 7v3h2v-3z"/>
    </svg>`;
  }

  function setHint(vannaChat, text) {
    const area = vannaChat?.shadowRoot?.querySelector(".chat-input-area");
    if (!area) return;

    let hint = area.querySelector(".voice-input-hint");
    if (!hint) {
      hint = document.createElement("div");
      hint.className = "voice-input-hint";
      hint.setAttribute("aria-live", "polite");
      area.appendChild(hint);
    }
    hint.textContent = text || "";
  }

  function setInputValue(input, value) {
    input.value = value;
    input.dispatchEvent(new Event("input", { bubbles: true, composed: true }));
  }

  function createController(vannaChat, button) {
    const recognition = new SpeechRecognition();
    recognition.lang = lang;
    recognition.continuous = continuous;
    recognition.interimResults = true;

    let listening = false;
    let baseText = "";

    recognition.onstart = () => {
      listening = true;
      const input = getMessageInput(vannaChat);
      baseText = input?.value.trim() || "";
      button.classList.add("is-listening");
      button.innerHTML = micIcon(true);
      button.setAttribute("aria-pressed", "true");
      setHint(vannaChat, "Đang nghe... Nói câu hỏi của bạn.");
    };

    recognition.onresult = (event) => {
      const input = getMessageInput(vannaChat);
      if (!input) return;

      let interim = "";
      let finalText = "";

      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        const text = result[0]?.transcript || "";
        if (result.isFinal) {
          finalText += text;
        } else {
          interim += text;
        }
      }

      const combined = `${finalText}${interim}`.trim();
      if (!combined) return;

      const prefix = baseText ? `${baseText} ` : "";
      setInputValue(input, `${prefix}${combined}`.trim());

      if (interim) {
        setHint(vannaChat, `Đang nghe: ${interim.trim()}`);
      }
    };

    recognition.onerror = (event) => {
      const messages = {
        "not-allowed": "Quyền micro bị từ chối. Hãy cho phép micro trong trình duyệt.",
        "service-not-allowed": "Nhận dạng giọng nói không khả dụng trên trang này.",
        "no-speech": "Không nghe thấy giọng nói. Hãy thử lại.",
        "audio-capture": "Không tìm thấy micro.",
        "network": "Lỗi mạng khi nhận dạng giọng nói.",
        aborted: "",
      };
      const message = messages[event.error] || `Lỗi nhận dạng giọng nói: ${event.error}`;
      if (message) {
        setHint(vannaChat, message);
      }
      stop();
    };

    recognition.onend = () => {
      stop();
      setHint(vannaChat, "");
    };

    function stop() {
      if (!listening) return;
      listening = false;
      button.classList.remove("is-listening");
      button.innerHTML = micIcon(false);
      button.setAttribute("aria-pressed", "false");
    }

    function start() {
      if (listening) {
        recognition.stop();
        return;
      }

      try {
        recognition.start();
      } catch (error) {
        if (error.name !== "InvalidStateError") {
          setHint(vannaChat, "Không thể bắt đầu ghi âm. Hãy thử lại.");
        }
      }
    }

    return { start, stop, recognition };
  }

  function injectVoiceButton(vannaChat) {
    const container = getInputContainer(vannaChat);
    if (!container || container.querySelector(".voice-input-button")) {
      return !!container?.querySelector(".voice-input-button");
    }

    injectStyles(vannaChat);

    const button = document.createElement("button");
    button.type = "button";
    button.className = "voice-input-button";
    button.setAttribute("aria-label", "Nhập bằng giọng nói");
    button.setAttribute("aria-pressed", "false");
    button.title = "Nhập bằng giọng nói";
    button.innerHTML = micIcon(false);

    const sendButton = container.querySelector(".send-button");
    container.insertBefore(button, sendButton);

    if (!SpeechRecognition) {
      button.disabled = true;
      button.title = "Trình duyệt không hỗ trợ nhận dạng giọng nói (dùng Chrome hoặc Edge)";
      setHint(
        vannaChat,
        "Nhận dạng giọng nói không được hỗ trợ. Hãy dùng Chrome hoặc Edge."
      );
      return true;
    }

    const controller = createController(vannaChat, button);
    button.addEventListener("click", () => controller.start());

    return true;
  }

  function setupVoiceInput() {
    const chatSections = document.getElementById("chatSections");
    if (chatSections?.classList.contains("hidden")) {
      return;
    }

    const vannaChat = getVannaChat();
    if (!vannaChat?.shadowRoot) {
      return;
    }

    injectVoiceButton(vannaChat);
  }

  function watchForChat() {
    setupVoiceInput();

    const observer = new MutationObserver(() => {
      setupVoiceInput();
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true,
    });

    const vannaChat = getVannaChat();
    if (vannaChat) {
      const shadowObserver = new MutationObserver(() => setupVoiceInput());
      const watchShadow = () => {
        if (vannaChat.shadowRoot) {
          shadowObserver.observe(vannaChat.shadowRoot, {
            childList: true,
            subtree: true,
          });
          setupVoiceInput();
        } else {
          requestAnimationFrame(watchShadow);
        }
      };
      watchShadow();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", watchForChat);
  } else {
    watchForChat();
  }

  document.getElementById("loginButton")?.addEventListener("click", () => {
    setTimeout(setupVoiceInput, 300);
  });
})();
