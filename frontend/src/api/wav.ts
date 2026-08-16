// The intake API sniffs magic bytes (services/intake_api/magic.py) and accepts only WAV, MP3,
// OGG and FLAC. MediaRecorder produces WebM/Opus on Chrome and Firefox, which that sniffer
// rejects, so microphone captures are decoded and re-encoded to 16-bit PCM WAV in the browser
// before upload rather than being sent in the container the recorder happened to choose.
//
// Whisper resamples to 16 kHz internally and the fused payload only ever uses the transcript,
// so the encoder downmixes to mono 16 kHz: it costs nothing in transcription quality and keeps
// a two-minute clip comfortably under the 25 MB attachment cap.

const TARGET_SAMPLE_RATE = 16_000;

/** Decode any container the browser can read, downmix to mono, resample to 16 kHz. */
async function decodeToMono16k(blob: Blob): Promise<AudioBuffer> {
  const bytes = await blob.arrayBuffer();

  // decodeAudioData needs a plain (non-offline) context: OfflineAudioContext cannot decode
  // every container on Safari. The context is closed immediately after decoding.
  const decodeContext = new AudioContext();
  let decoded: AudioBuffer;
  try {
    decoded = await decodeContext.decodeAudioData(bytes);
  } finally {
    void decodeContext.close();
  }

  const frames = Math.ceil((decoded.duration * TARGET_SAMPLE_RATE));
  const offline = new OfflineAudioContext(1, Math.max(frames, 1), TARGET_SAMPLE_RATE);
  const source = offline.createBufferSource();
  source.buffer = decoded;
  source.connect(offline.destination);
  source.start(0);
  return offline.startRendering();
}

function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  const bytesPerSample = 2;
  const buffer = new ArrayBuffer(44 + samples.length * bytesPerSample);
  const view = new DataView(buffer);

  const writeAscii = (offset: number, text: string) => {
    for (let i = 0; i < text.length; i += 1) view.setUint8(offset + i, text.charCodeAt(i));
  };

  const dataBytes = samples.length * bytesPerSample;
  writeAscii(0, "RIFF");
  view.setUint32(4, 36 + dataBytes, true);
  writeAscii(8, "WAVE");
  writeAscii(12, "fmt ");
  view.setUint32(16, 16, true); // PCM header size
  view.setUint16(20, 1, true); // format 1 = PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * bytesPerSample, true); // byte rate
  view.setUint16(32, bytesPerSample, true); // block align
  view.setUint16(34, 8 * bytesPerSample, true); // bits per sample
  writeAscii(36, "data");
  view.setUint32(40, dataBytes, true);

  let offset = 44;
  for (let i = 0; i < samples.length; i += 1) {
    // Clamp before scaling: values outside [-1, 1] would otherwise wrap and click.
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
    offset += bytesPerSample;
  }

  return new Blob([view], { type: "audio/wav" });
}

/** Re-encode a recorded blob as mono 16 kHz PCM WAV that the intake sniffer accepts. */
export async function toWav(blob: Blob): Promise<Blob> {
  const rendered = await decodeToMono16k(blob);
  return encodeWav(rendered.getChannelData(0), rendered.sampleRate);
}
