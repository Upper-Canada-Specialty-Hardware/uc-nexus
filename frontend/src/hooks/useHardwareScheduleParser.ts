import { useState, useCallback, useRef, useEffect } from 'react';
import type { ParseResult, WorkerOutboundMessage, WorkerParseRequest } from '../types/hardwareSchedule';

export type ParserState = 'idle' | 'reading' | 'parsing' | 'done' | 'error';

export const WORKER_START_FAILED =
  "The file reader couldn't start, most likely because the app was updated. Reload the page and try again.";

export interface ParserProgress {
  percent: number;
  phase: string;
}

export interface UseHardwareScheduleParserReturn {
  state: ParserState;
  progress: ParserProgress;
  parseResult: ParseResult | null;
  error: string | null;
  isLoading: boolean;
  parseFile: (file: File) => void;
  hydrate: (result: ParseResult) => void;
  setLoading: (phase: string) => void;
  setError: (message: string) => void;
  reset: () => void;
}

export function useHardwareScheduleParser(): UseHardwareScheduleParserReturn {
  const [state, setState] = useState<ParserState>('idle');
  const [progress, setProgress] = useState<ParserProgress>({ percent: 0, phase: '' });
  const [result, setResult] = useState<ParseResult | null>(null);
  const [error, setErrorState] = useState<string | null>(null);

  const workerRef = useRef<Worker | null>(null);
  // #1455: the read in flight and which parse it belongs to. Closing the wizard (reset, unmount) during
  // "Reading file" found no worker to stop yet; the read then finished and started one that nothing
  // ever terminated. A read whose generation is stale returns before it creates the worker.
  const readerRef = useRef<FileReader | null>(null);
  const generationRef = useRef(0);

  const cancelRead = useCallback(() => {
    generationRef.current += 1;
    const reader = readerRef.current;
    readerRef.current = null;
    // A no-op on a read that already finished; the generation check is what stops a late onload.
    reader?.abort();
  }, []);

  const parseFile = useCallback((file: File) => {
    if (state === 'reading' || state === 'parsing') {
      return;
    }

    setState('reading');
    setProgress({ percent: 0, phase: 'Reading file' });
    setResult(null);
    setErrorState(null);

    const generation = ++generationRef.current;
    const reader = new FileReader();
    readerRef.current = reader;
    reader.readAsText(file);

    reader.onload = () => {
      if (generation !== generationRef.current) return;
      readerRef.current = null;
      setState('parsing');

      if (!workerRef.current) {
        workerRef.current = new Worker(
          new URL('../workers/hardwareScheduleParser.worker.ts', import.meta.url),
          { type: 'module' }
        );
      }

      const worker = workerRef.current;

      worker.onmessage = (event: MessageEvent<WorkerOutboundMessage>) => {
        const message = event.data;

        switch (message.type) {
          case 'progress':
            setProgress({ percent: message.percent, phase: message.phase });
            break;
          case 'result':
            setResult(message.data);
            setState('done');
            setProgress({ percent: 100, phase: 'Complete' });
            break;
          case 'error':
            setErrorState(message.error);
            setState('error');
            break;
        }
      };

      // #1920: the worker is its own hashed file, so a tab opened before a deploy asks for one that is
      // gone. The failed load's error has no message (an empty red alert), and the broken worker was
      // kept, so every try again failed the same way. It is dropped, so the next try starts a new one,
      // and a load failure says what will fix it. The worker posts its own parse errors as messages.
      worker.onerror = (event: ErrorEvent) => {
        worker.terminate();
        if (workerRef.current === worker) workerRef.current = null;
        setErrorState(event.message || WORKER_START_FAILED);
        setState('error');
      };

      const request: WorkerParseRequest = {
        type: 'parse',
        xmlContent: reader.result as string,
      };
      worker.postMessage(request);
    };

    reader.onerror = () => {
      if (generation !== generationRef.current) return;
      readerRef.current = null;
      setErrorState('Failed to read file');
      setState('error');
    };
  }, [state]);

  const hydrate = useCallback((parseResult: ParseResult) => {
    cancelRead();
    if (workerRef.current) {
      workerRef.current.terminate();
      workerRef.current = null;
    }
    setResult(parseResult);
    setState('done');
    setProgress({ percent: 100, phase: 'Complete' });
    setErrorState(null);
  }, [cancelRead]);

  const setLoading = useCallback((phase: string) => {
    setState('reading');
    setProgress({ percent: 0, phase });
    setErrorState(null);
  }, []);

  const setError = useCallback((message: string) => {
    setState('error');
    setErrorState(message);
  }, []);

  const reset = useCallback(() => {
    cancelRead();
    if (workerRef.current) {
      workerRef.current.terminate();
      workerRef.current = null;
    }

    setState('idle');
    setProgress({ percent: 0, phase: '' });
    setResult(null);
    setErrorState(null);
  }, [cancelRead]);

  useEffect(() => {
    return () => {
      cancelRead();
      if (workerRef.current) {
        workerRef.current.terminate();
      }
    };
  }, [cancelRead]);

  const isLoading = state === 'reading' || state === 'parsing';

  return {
    state,
    progress,
    parseResult: result,
    error,
    isLoading,
    parseFile,
    hydrate,
    setLoading,
    setError,
    reset,
  };
}
