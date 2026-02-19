/// <reference lib="webworker" />

import { parseHardwareSchedule } from './parserLogic';
import type { WorkerParseRequest, WorkerOutboundMessage } from '../types/hardwareSchedule';

declare const self: DedicatedWorkerGlobalScope;

self.onmessage = (event: MessageEvent<WorkerParseRequest>) => {
  if (event.data.type !== 'parse') return;

  try {
    const result = parseHardwareSchedule(event.data.xmlContent, (percent, phase) => {
      const msg: WorkerOutboundMessage = { type: 'progress', percent, phase };
      self.postMessage(msg);
    });

    const msg: WorkerOutboundMessage = { type: 'result', data: result };
    self.postMessage(msg);
  } catch (err) {
    const msg: WorkerOutboundMessage = {
      type: 'error',
      error: err instanceof Error ? err.message : String(err),
    };
    self.postMessage(msg);
  }
};
