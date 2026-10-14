import { parseHardwareSchedule } from '../../workers/parserLogic';
import { checkJobNumber } from '../../modules/import/jobNumberCheck';
import { SAMPLE_SCHEDULE_OPENING_COUNT, demoSampleScheduleXml } from '../sampleSchedule';

// #1637: the sample schedule is read by the real parser exactly as a TITAN export is.

it('parses cleanly into openings and hardware, every opening carrying some', () => {
  const result = parseHardwareSchedule(demoSampleScheduleXml('DEMO-1004'));
  expect(result.openings).toHaveLength(SAMPLE_SCHEDULE_OPENING_COUNT);
  expect(result.validationSummary.skippedRows).toEqual([]);
  const withHardware = new Set(result.hardwareItems.map((h) => h.opening_number));
  expect(withHardware.size).toBe(SAMPLE_SCHEDULE_OPENING_COUNT);
  // The exit door gets the exit device; the offices get locksets.
  expect(result.hardwareItems.filter((h) => h.hardware_category === 'EXIT').map((h) => h.opening_number)).toEqual([
    'R06',
  ]);
  expect(result.hardwareItems.find((h) => h.hardware_category === 'LOCKSET')?.manufacturer).toBe('Schlage');
});

it("names the chosen project's job, so the wizard's job check matches", () => {
  const result = parseHardwareSchedule(demoSampleScheduleXml('DEMO-1004'));
  expect(checkJobNumber(result.project.submittal_job_no, 'DEMO-1004')).toBe('match');
});
