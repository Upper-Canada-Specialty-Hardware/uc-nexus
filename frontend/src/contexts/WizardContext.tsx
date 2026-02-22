import { createContext, useContext, useState, useCallback, type ReactNode } from 'react';

interface WizardContextType {
  currentStep: number;
  formData: Record<string, unknown>;
  totalSteps: number;
  setStep: (step: number) => void;
  setFormData: (data: Record<string, unknown>) => void;
  updateFormData: (key: string, value: unknown) => void;
  setTotalSteps: (total: number) => void;
  reset: () => void;
  isActive: boolean;
}

const WizardContext = createContext<WizardContextType | undefined>(undefined);

export function WizardProvider({ children }: { children: ReactNode }) {
  const [currentStep, setCurrentStep] = useState(0);
  const [formData, setFormDataState] = useState<Record<string, unknown>>({});
  const [totalSteps, setTotalSteps] = useState(0);

  const reset = useCallback(() => {
    setCurrentStep(0);
    setFormDataState({});
    setTotalSteps(0);
  }, []);

  const updateFormData = useCallback((key: string, value: unknown) => {
    setFormDataState((prev) => ({ ...prev, [key]: value }));
  }, []);

  return (
    <WizardContext.Provider
      value={{
        currentStep,
        formData,
        totalSteps,
        setStep: setCurrentStep,
        setFormData: setFormDataState,
        updateFormData,
        setTotalSteps,
        reset,
        isActive: totalSteps > 0,
      }}
    >
      {children}
    </WizardContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useWizard() {
  const context = useContext(WizardContext);
  if (!context) throw new Error('useWizard must be used within WizardProvider');
  return context;
}
