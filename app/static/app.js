/* reaper-monitor 前端逻辑：选人页 + 混音页。 */
(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const page = document.body.dataset.page;

  if (page === "pick") initPick();
  if (page === "mix") initMix();

  // ------------------------------------------------------------------ 选人页

  async function initPick() {
    const list = $("#musician-list");
    const banner = $("#error-banner");
    $("#lan-hint").textContent = location.origin + "/";
    await refreshPick(list, banner);
    // 监听轨道是 REAPER 里实际创建的，轮询让页面在 REAPER 打开后自动出现通道
    setInterval(() => refreshPick(list, banner), 3000);
  }

  async function refreshPick(list, banner) {
    let cfg;
    try {
      cfg = await (await fetch("/api/config")).json();
    } catch (err) {
      showBanner(banner, "无法连接服务器，请确认监听服务已启动，且手机与电脑在同一局域网。");
      return;
    }
    const monitors = cfg.monitors || [];
    $("#pick-count").textContent = monitors.length + " 条监听轨道";
    if (!monitors.length) {
      list.innerHTML = '<p class="muted empty-hint">未发现监听轨道。<br>请确认 REAPER 已打开工程、已加载 OSC 控制面，且监听母线轨道名以 “' +
        escapeHtml(cfg.monitor_prefix || "MON ") + '” 开头。<br>页面每 3 秒自动刷新。</p>';
      return;
    }
    list.innerHTML = "";
    for (const m of monitors) {
      const btn = document.createElement("a");
      btn.className = "pick-btn";
      btn.href = "/mix.html?id=" + encodeURIComponent(m.id);
      btn.innerHTML = "<span>" + escapeHtml(m.name) + "</span><span class='arrow'>›</span>";
      list.appendChild(btn);
    }
  }

  // ------------------------------------------------------------------ 混音页

  function initMix() {
    const id = new URLSearchParams(location.search).get("id");
    if (!id) { location.href = "/"; return; }

    const banner = $("#error-banner");
    const nameEl = $("#musician-name");
    const statusEl = $("#stream-status");
    const masterLevel = $("#master-level");
    const masterValue = $("#master-value");
    const masterMute = $("#master-mute");
    const sourceList = $("#source-list");

    let config = null;
    let controlWs = null;
    let controlRetry = null;
    let audioWs = null;
    let audioRetry = null;
    let audioCtx = null;
    let workletNode = null;
    let scriptNode = null;
    let channels = 0;
    let sampleRate = 0;
    let pcm = null;
    let pcmCap = 0;
    let pcmHead = 0;
    let pcmTail = 0;
    let pcmCount = 0;

    // ---- 配置与界面骨架
    fetch("/api/config")
      .then((r) => r.json())
      .then((cfg) => {
        config = cfg;
        const monitor = (cfg.monitors || []).find((m) => m.id === id);
        if (!monitor) {
          showBanner(banner, "没有这条监听轨道，可能 REAPER 工程已变化。请回选人页重新选择。");
          return;
        }
        nameEl.textContent = monitor.name;
        document.title = "监听 · " + monitor.name;
        renderSources(cfg.sources || []);
        connectControlWs();
        connectAudioWs();
      })
      .catch(() => showBanner(banner, "无法加载配置，请确认服务已启动。"));

    function renderSources(sources) {
      sourceList.innerHTML = "";
      sources.forEach((name, i) => {
        const row = document.createElement("li");
        row.className = "source-row";
        row.innerHTML =
          '<span class="source-name">' + escapeHtml(name) + "</span>" +
          '<button class="mute-btn small" aria-pressed="false" title="静音/恢复">M</button>' +
          '<input type="range" min="0" max="1" step="0.01" value="0.75" aria-label="' + escapeHtml(name) + ' 响度" autocomplete="off">' +
          '<span class="source-value muted value">75%</span>';
        const slider = row.querySelector("input[type=range]");
        const valueEl = row.querySelector(".source-value");
        const muteBtn = row.querySelector(".mute-btn");
        slider.addEventListener("input", () => {
          valueEl.textContent = Math.round(slider.value * 100) + "%";
          sendControl({ type: "set_source_level", index: i, value: parseFloat(slider.value) });
        });
        muteBtn.addEventListener("click", () => {
          const muted = muteBtn.getAttribute("aria-pressed") !== "true";
          muteBtn.setAttribute("aria-pressed", String(muted));
          row.classList.toggle("muted", muted);
          sendControl({ type: "set_source_mute", index: i, muted });
        });
        sourceList.appendChild(row);
      });
    }

    // ---- 控制通道（自动重连）

    function connectControlWs() {
      controlWs = new WebSocket(wsUrl("/ws/control/" + encodeURIComponent(id)));
      controlWs.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.type === "state") applyState(msg);
        else if (msg.type === "error") showBanner(banner, msg.message);
      };
      controlWs.onclose = () => {
        if (controlRetry) return;
        controlRetry = setTimeout(() => { controlRetry = null; connectControlWs(); }, 2000);
      };
    }

    function applyState(state) {
      state.sources.forEach((s) => {
        const row = sourceList.children[s.index];
        if (!row) return;
        const slider = row.querySelector("input[type=range]");
        const valueEl = row.querySelector(".source-value");
        const muteBtn = row.querySelector(".mute-btn");
        slider.value = s.level;
        valueEl.textContent = Math.round(s.level * 100) + "%";
        muteBtn.setAttribute("aria-pressed", String(s.muted));
        row.classList.toggle("muted", s.muted);
      });
      masterLevel.value = state.master.level;
      masterValue.textContent = Math.round(state.master.level * 100) + "%";
      masterMute.setAttribute("aria-pressed", String(state.master.muted));
    }

    const sendControl = makeSender((msg) => {
      if (controlWs && controlWs.readyState === WebSocket.OPEN) controlWs.send(JSON.stringify(msg));
    }, 40);

    // ---- 总音量 / 总静音

    masterLevel.addEventListener("input", () => {
      masterValue.textContent = Math.round(masterLevel.value * 100) + "%";
      sendControl({ type: "set_master_level", value: parseFloat(masterLevel.value) });
    });

    masterMute.addEventListener("click", () => {
      const muted = masterMute.getAttribute("aria-pressed") !== "true";
      masterMute.setAttribute("aria-pressed", String(muted));
      sendControl({ type: "set_master_mute", muted });
    });

    // ---- 音频通道（自动重连）

    function connectAudioWs() {
      audioWs = new WebSocket(wsUrl("/ws/audio/" + encodeURIComponent(id)));
      audioWs.binaryType = "arraybuffer";
      audioWs.onmessage = (ev) => {
        if (typeof ev.data === "string") {
          const msg = JSON.parse(ev.data);
          if (msg.type === "stream_info") initAudio(msg);
          return;
        }
        onAudioBlock(ev.data);
      };
      audioWs.onclose = () => {
        setStatus("音频已断开，重连中…");
        if (audioRetry) return;
        audioRetry = setTimeout(() => { audioRetry = null; connectAudioWs(); }, 2000);
      };
      audioWs.onopen = () => setStatus("已连接，等待音频…");
    }

    async function initAudio(info) {
      channels = info.channels;
      sampleRate = info.sampleRate;
      try {
        if (audioCtx && audioCtx.sampleRate === sampleRate && (workletNode || scriptNode)) { updateAudioStatus(); return; }
      } catch (_) { /* 继续重建 */ }
      try {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate });
      } catch (_) {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      }
      try {
        if (audioCtx.audioWorklet && audioCtx.audioWorklet.addModule) {
          await audioCtx.audioWorklet.addModule("/audio-worklet.js");
          workletNode = new AudioWorkletNode(audioCtx, "monitor-processor", {
            numberOfInputs: 0,
            numberOfOutputs: 1,
            outputChannelCount: [channels],
          });
          workletNode.connect(audioCtx.destination);
        } else {
          setupScriptProcessor();
        }
        if (audioCtx.sampleRate !== sampleRate) {
          showBanner(banner, "采样率不匹配：REAPER " + sampleRate + "Hz，本机 " + audioCtx.sampleRate + "Hz，声音可能变调。");
        }
        updateAudioStatus();
      } catch (err) {
        showBanner(banner, "音频初始化失败：" + err.message);
      }
    }

    function onAudioBlock(buf) {
      if (!channels || (!workletNode && !scriptNode)) return;
      const planar = new Float32Array(buf);
      const frames = planar.length / channels;
      const interleaved = new Float32Array(planar.length);
      for (let ch = 0; ch < channels; ch++) {
        const src = ch * frames;
        for (let f = 0; f < frames; f++) interleaved[f * channels + ch] = planar[src + f];
      }
      if (workletNode) {
        workletNode.port.postMessage(interleaved, [interleaved.buffer]);
      } else {
        pcmPush(interleaved);
      }
    }

    // ---- 旧 iOS Safari 无 AudioWorklet 时回退 ScriptProcessor（延迟略高但可用）
    function setupScriptProcessor() {
      pcm = null; pcmCap = 0; pcmHead = 0; pcmTail = 0; pcmCount = 0;
      // 延迟优先：老 iOS 上 ScriptProcessor 的回调块就是输出延迟下限，先试 1024 帧（≈21ms@48k），不行再 2048。
      scriptNode = null;
      for (const bufferSize of [1024, 2048]) {
        for (const inputCh of [0, 1]) {
          try {
            scriptNode = audioCtx.createScriptProcessor(bufferSize, inputCh, channels);
            break;
          } catch (_) { /* 某些实现不接受 0 输入或不支持该块大小 */ }
        }
        if (scriptNode) break;
      }
      if (!scriptNode) throw new Error("无法创建音频处理器");
      scriptNode.onaudioprocess = (ev) => {
        const out = ev.outputBuffer;
        const outLen = out.length;
        const needed = outLen * channels;
        const outChs = [];
        for (let ch = 0; ch < channels; ch++) outChs.push(out.getChannelData(ch));
        if (pcm && pcmCount >= needed) {
          for (let i = 0; i < outLen; i++) {
            for (let ch = 0; ch < channels; ch++) {
              outChs[ch][i] = pcm[pcmTail];
              pcmTail = (pcmTail + 1) % pcmCap;
            }
          }
          pcmCount -= needed;
        } else {
          for (let ch = 0; ch < channels; ch++) outChs[ch].fill(0);
        }
      };
      scriptNode.connect(audioCtx.destination);
    }

    function pcmPush(data) {
      if (!pcm || pcmCap !== 8192 * channels) {
        pcmCap = 8192 * channels;
        pcm = new Float32Array(pcmCap);
        pcmHead = 0; pcmTail = 0; pcmCount = 0;
      }
      if (data.length >= pcmCap) {
        pcm.set(data.subarray(data.length - pcmCap), 0);
        pcmHead = 0; pcmTail = 0; pcmCount = pcmCap;
        return;
      }
      if (data.length > pcmCap - pcmCount) {
        const drop = data.length - (pcmCap - pcmCount);
        pcmTail = (pcmTail + drop) % pcmCap;
        pcmCount -= drop;
      }
      for (let i = 0; i < data.length; i++) {
        pcm[pcmHead] = data[i];
        pcmHead = (pcmHead + 1) % pcmCap;
      }
      pcmCount += data.length;
    }

    // iOS/Android 需要用户手势后才能出声：initAudio 里不 await resume()（无手势时它会一直挂起或被拒），
    // 改为每次触摸时唤醒，并把状态同步到页面上。
    function resumeAudio() {
      if (!audioCtx) return;
      if (audioCtx.state === "suspended") {
        audioCtx.resume().then(updateAudioStatus).catch(() => updateAudioStatus());
      } else {
        updateAudioStatus();
      }
    }
    document.addEventListener("pointerdown", resumeAudio);
    document.addEventListener("touchstart", resumeAudio);

    function updateAudioStatus() {
      if (!audioCtx) { setStatus("已连接，等待音频…"); return; }
      if (audioCtx.state === "suspended") {
        setStatus("音频已就绪，点一下屏幕开始播放");
      } else {
        setStatus("音频已连接");
      }
    }

    function setStatus(text) { statusEl.textContent = text; }
  }

  // ------------------------------------------------------------------ 工具

  function wsUrl(path) {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    return proto + "//" + location.host + path;
  }

  function showBanner(el, text) {
    el.textContent = text;
    el.classList.remove("hidden");
    clearTimeout(el._timer);
    el._timer = setTimeout(() => el.classList.add("hidden"), 8000);
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);
  }

  function makeSender(fn, interval) {
    let last = 0;
    let timer = null;
    let pending = null;
    return (msg) => {
      const now = Date.now();
      pending = msg;
      if (now - last >= interval) {
        last = now;
        pending = null;
        fn(msg);
      } else if (!timer) {
        timer = setTimeout(() => {
          timer = null;
          last = Date.now();
          if (pending !== null) { fn(pending); pending = null; }
        }, interval - (now - last));
      }
    };
  }
})();
