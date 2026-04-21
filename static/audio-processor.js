class AudioProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    // Buffer for ~256ms of audio at 16kHz (16000 * 0.256 = 4096)
    this.bufferSize = 4096;
    this.buffer = new Int16Array(this.bufferSize);
    this.bufferIndex = 0;
  }

  process(inputs, outputs, parameters) {
    const input = inputs[0];
    if (input.length > 0) {
      const inputChannel = input[0];

      // Convert Float32 to Int16 and add to our buffer
      for (let i = 0; i < inputChannel.length; i++) {
        // Ensure we don't overflow the buffer
        if (this.bufferIndex >= this.bufferSize) {
          break;
        }
        this.buffer[this.bufferIndex++] = Math.max(-1, Math.min(1, inputChannel[i])) * 32767;
      }

      // When the buffer is full, send it to the main thread
      if (this.bufferIndex >= this.bufferSize) {
        // Post a copy of the buffer's content
        this.port.postMessage(this.buffer.slice(0, this.bufferIndex));
        
        // Reset buffer for the next chunk
        this.bufferIndex = 0;
      }
    }
    return true; // Keep processor alive
  }
}

registerProcessor('audio-processor', AudioProcessor);