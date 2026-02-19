import { render, screen, fireEvent } from '@testing-library/react';
import ValidationSummaryDisplay from '../ValidationSummaryDisplay';
import type { ValidationSummary } from '../../types/hardwareSchedule';

describe('ValidationSummaryDisplay', () => {
  it('renders success state when there are no skipped rows or warnings', () => {
    const summary: ValidationSummary = {
      totalOpenings: 100,
      totalHardwareItems: 500,
      skippedRows: [],
      warnings: [],
    };

    render(<ValidationSummaryDisplay summary={summary} />);

    expect(screen.getByText('100 openings parsed')).toBeInTheDocument();
    expect(screen.getByText('500 hardware items parsed')).toBeInTheDocument();
    expect(screen.getByText('All rows parsed successfully')).toBeInTheDocument();

    // The success alert should have role="alert"
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('All rows parsed successfully');
  });

  it('displays skipped rows with warning severity', () => {
    const summary: ValidationSummary = {
      totalOpenings: 98,
      totalHardwareItems: 490,
      skippedRows: [
        { reason: 'Missing Opening_Number', context: 'Opening index 5' },
        { reason: 'Item_Quantity must be > 0', context: 'Product_Code: LOCK-100' },
      ],
      warnings: [],
    };

    render(<ValidationSummaryDisplay summary={summary} />);

    expect(screen.getByText('98 openings parsed')).toBeInTheDocument();
    expect(screen.getByText('490 hardware items parsed')).toBeInTheDocument();
    expect(screen.getByText('2 rows skipped')).toBeInTheDocument();

    // Both skip reasons and their contexts should be visible
    expect(screen.getByText('Missing Opening_Number')).toBeInTheDocument();
    expect(screen.getByText('Opening index 5')).toBeInTheDocument();
    expect(screen.getByText('Item_Quantity must be > 0')).toBeInTheDocument();
    expect(screen.getByText('Product_Code: LOCK-100')).toBeInTheDocument();

    // Success message should NOT be present
    expect(screen.queryByText('All rows parsed successfully')).not.toBeInTheDocument();
  });

  it('displays warnings in an info alert', () => {
    const summary: ValidationSummary = {
      totalOpenings: 100,
      totalHardwareItems: 500,
      skippedRows: [],
      warnings: ['3 openings had no hardware items assigned'],
    };

    render(<ValidationSummaryDisplay summary={summary} />);

    expect(screen.getByText('3 openings had no hardware items assigned')).toBeInTheDocument();

    // Success message should NOT be present when there are warnings
    expect(screen.queryByText('All rows parsed successfully')).not.toBeInTheDocument();
  });

  it('collapses rows beyond 10 and toggles with Show all / Show fewer button', () => {
    const skippedRows = Array.from({ length: 15 }, (_, i) => ({
      reason: `Reason ${i + 1}`,
      context: `Context ${i + 1}`,
    }));

    const summary: ValidationSummary = {
      totalOpenings: 85,
      totalHardwareItems: 400,
      skippedRows,
      warnings: [],
    };

    render(<ValidationSummaryDisplay summary={summary} />);

    expect(screen.getByText('15 rows skipped')).toBeInTheDocument();

    // First 10 should be visible
    for (let i = 1; i <= 10; i++) {
      expect(screen.getByText(`Reason ${i}`)).toBeInTheDocument();
    }

    // Items 11-15 should be in the document but inside a collapsed Collapse
    // They are rendered but hidden via MUI Collapse (visibility/height)
    // The "Show all" button should be present
    const showAllButton = screen.getByRole('button', { name: /Show all 15 skipped rows/i });
    expect(showAllButton).toBeInTheDocument();

    // Click "Show all" to expand
    fireEvent.click(showAllButton);

    // All 15 reasons should now be visible
    for (let i = 1; i <= 15; i++) {
      expect(screen.getByText(`Reason ${i}`)).toBeInTheDocument();
    }

    // Button text should change to "Show fewer"
    expect(screen.getByRole('button', { name: /Show fewer/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Show all/i })).not.toBeInTheDocument();

    // Click "Show fewer" to collapse again
    fireEvent.click(screen.getByRole('button', { name: /Show fewer/i }));

    // Button should revert to "Show all"
    expect(screen.getByRole('button', { name: /Show all 15 skipped rows/i })).toBeInTheDocument();
  });

  it('does not show collapse button when there are exactly 10 skipped rows', () => {
    const skippedRows = Array.from({ length: 10 }, (_, i) => ({
      reason: `Reason ${i + 1}`,
      context: `Context ${i + 1}`,
    }));

    const summary: ValidationSummary = {
      totalOpenings: 90,
      totalHardwareItems: 450,
      skippedRows,
      warnings: [],
    };

    render(<ValidationSummaryDisplay summary={summary} />);

    expect(screen.getByText('10 rows skipped')).toBeInTheDocument();

    // All 10 should be visible
    for (let i = 1; i <= 10; i++) {
      expect(screen.getByText(`Reason ${i}`)).toBeInTheDocument();
    }

    // No "Show all" button since there are exactly 10 (not more than 10)
    expect(screen.queryByRole('button', { name: /Show all/i })).not.toBeInTheDocument();
  });

  it('renders both skipped rows and warnings simultaneously', () => {
    const summary: ValidationSummary = {
      totalOpenings: 95,
      totalHardwareItems: 480,
      skippedRows: [
        { reason: 'Missing Opening_Number', context: 'Opening index 3' },
      ],
      warnings: ['5 openings had no hardware items assigned'],
    };

    render(<ValidationSummaryDisplay summary={summary} />);

    expect(screen.getByText('95 openings parsed')).toBeInTheDocument();
    expect(screen.getByText('480 hardware items parsed')).toBeInTheDocument();

    // Skipped row section
    expect(screen.getByText('1 rows skipped')).toBeInTheDocument();
    expect(screen.getByText('Missing Opening_Number')).toBeInTheDocument();
    expect(screen.getByText('Opening index 3')).toBeInTheDocument();

    // Warning section
    expect(screen.getByText('5 openings had no hardware items assigned')).toBeInTheDocument();

    // Success message should NOT be present
    expect(screen.queryByText('All rows parsed successfully')).not.toBeInTheDocument();

    // There should be two alerts (warning + info)
    const alerts = screen.getAllByRole('alert');
    expect(alerts).toHaveLength(2);
  });
});
