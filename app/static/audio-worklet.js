/* reaper-monitor 播放 Worklet：单生产者环形缓冲，欠载时输出静音。 */
class MonitorProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buffer = new Float32Array(32768); // ≈0.37s @44.1k 双声道
    this._writePos = 0;
    this._readPos = 0;
    this.port.onmessage = (e) => {
      const data = e.data;
      const cap = this._buffer.length;
      let wp = this._writePos;
      const avail = (wp - this._readPos + cap) % cap;
      if (data.length > avail - 1) {
        // 缓冲将溢出：丢最旧样本，保持低延迟
        this._readPos = (this._readPos + (data.length - (avail - 1))) % cap;
      }
      for (let i = 0; i < data.length; i++) {
        this._buffer[wp] = data[i];
        wp = (wp + 1) % cap;
      }
      this._writePos = wp;
    };
  }

  process(inputs, outputs) {
    const out = outputs[0];
    if (!out || out.length === 0) return true;
    const cap = this._buffer.length;
    const frames = out[0].length;
    const nCh = out.length;
    for (let f = 0; f < frames; f++) {
      for (let ch = 0; ch < nCh; ch++) {
        if (this._readPos !== this._writePos) {
          out[ch][f] = this._buffer[this._readPos];
          this._readPos = (this._readPos + 1) % cap;
        } else {
          out[ch][f] = 0; // 欠载：静音
        }
      }
    }
    return true;
  }
}

registerProcessor('monitor-processor', MonitorProcessor);
