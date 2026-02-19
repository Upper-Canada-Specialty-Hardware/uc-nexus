import { useState, useCallback, useRef, useEffect } from 'react';
import type { ParseResult, WorkerOutboundMessage, WorkerParseRequest } from '../types/hardwareSchedule';

export type ParserState = 'idle' | 'reading' | 'parsing' | 'done' | 'error';

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
  reset: () => void;
}

export function useHardwareScheduleParser(): UseHardwareScheduleParserReturn {
  const [state, setState] = useState<ParserState>('idle');
  const [progress, setProgress] = useState<ParserProgress>({ percent: 0, phase: '' });
  const [result, setResult] = useState<ParseResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const workerRef = useRef<Worker | null>(null);

  const parseFile = useCallback((file: File) => {
    if (state === 'reading' || state === 'parsing') {
      return;
    }

    setState('reading');
    setProgress({ percent: 0, phase: 'Reading file' });
    setResult(null);
    setError(null);

    const reader = new FileReader();
    reader.readAsText(file);

    reader.onload = () => {
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
            setError(message.error);
            setState('error');
            break;
        }
      };

      worker.onerror = (event: ErrorEvent) => {
        setError(event.message);
        setState('error');
      };

      const request: WorkerParseRequest = {
        type: 'parse',
        xmlContent: reader.result as string,
      };
      worker.postMessage(request);
    };

    reader.onerror = () => {
      setError('Failed to read file');
      setState('error');
    };
  }, [state]);

  const reset = useCallback(() => {
    if (workerRef.current) {
      workerRef.current.terminate();
      workerRef.current = null;
    }

    setState('idle');
    setProgress({ percent: 0, phase: '' });
    setResult(null);
    setError(null);
  }, []);

  useEffect(() => {
    return () => {
      if (workerRef.current) {
        workerRef.current.terminate();
      }
    };
  }, []);

  const isLoading = state === 'reading' || state === 'parsing';

  return {
    state,
    progress,
    parseResult: result,
    error,
    isLoading,
    parseFile,
    reset,
  };
}
