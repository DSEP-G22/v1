import { useCallback, useEffect, useRef, useState } from "react";

import { toWav } from "./wav";

// Microphone capture for the submission page. MediaRecorder gives us whatever container the
// browser prefers; toWav() converts it to a format the intake sniffer accepts. The track is
// stopped on every exit path so the browser's recording indicator does not stay lit.

export type RecorderState = "idle" | "recording" | "encoding";

export function useRecorder() {
  const [state, setState] = useState<RecorderState>("idle");
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const tickRef = useRef<number | null>(null);

  const releaseStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (tickRef.current !== null) {
      window.clearInterval(tickRef.current);
      tickRef.current = null;
    }
  }, []);

  // Releasing on unmount matters: navigating away mid-recording would otherwise leave the
  // microphone open for the lifetime of the tab.
  useEffect(() => releaseStream, [releaseStream]);

  const start = useCallback(async () => {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      chunksRef.current = [];

      const recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.start();
      recorderRef.current = recorder;

      setSeconds(0);
      tickRef.current = window.setInterval(() => setSeconds((s) => s + 1), 1000);
      setState("recording");
    } catch {
      // Overwhelmingly a denied permission prompt; a missing device reads the same to the user.
      setError("Microphone unavailable. Grant permission, or upload an audio file instead.");
      releaseStream();
      setState("idle");
    }
  }, [releaseStream]);

  /** Resolves with a WAV blob, or null if encoding failed. */
  const stop = useCallback(async (): Promise<File | null> => {
    const recorder = recorderRef.current;
    if (!recorder) return null;

    setState("encoding");
    const raw = await new Promise<Blob>((resolve) => {
      recorder.onstop = () => resolve(new Blob(chunksRef.current, { type: recorder.mimeType }));
      recorder.stop();
    });
    releaseStream();
    recorderRef.current = null;

    try {
      const wav = await toWav(raw);
      setState("idle");
      return new File([wav], `recording-${Date.now()}.wav`, { type: "audio/wav" });
    } catch {
      setError("Could not encode the recording. Try uploading an audio file instead.");
      setState("idle");
      return null;
    }
  }, [releaseStream]);

  const cancel = useCallback(() => {
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      recorder.onstop = null;
      recorder.stop();
    }
    recorderRef.current = null;
    chunksRef.current = [];
    releaseStream();
    setSeconds(0);
    setState("idle");
  }, [releaseStream]);

  return { state, seconds, error, start, stop, cancel };
}
