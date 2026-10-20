import { useState, type ReactNode } from 'react';
import {
  Box, Typography, TextField, Button, Stack, Alert, CircularProgress,
} from '@mui/material';
import { useQuery, useMutation } from '@apollo/client/react';
import {
  GET_COMPANY_LETTERHEAD, GET_PO_DOCUMENT_SETTINGS, SET_COMPANY_ADDRESS, UPDATE_PO_DOCUMENT_SETTINGS,
} from '../../graphql/po';
import type { CompanyLetterhead } from '../../company/letterhead';
import { useActingCompany } from '../../company/ActingCompanyContext';
import { useToast } from '../../components/Toast';
import { useIdentity } from '../../hooks/useIdentity';
import PageHeader from '../../components/PageHeader';
import { microLabelSx } from '../../theme';
import { FadeIn } from '../../motion';
import { userMessage } from '../../graphql/userMessage';

/** A 2px ink rule with a micro-label heading — the section separator used across the PO module. */
function SectionHeading({ children }: { children: ReactNode }) {
  return (
    <Box sx={{ pt: 1.5, borderTop: '2px solid', borderColor: 'text.primary' }}>
      <Typography component="h2" sx={microLabelSx}>
        {children}
      </Typography>
    </Box>
  );
}

interface PODocumentSettings {
  taxNumbers: string;
  mandatoryBullets: string[];
  shippingAccounts: string[];
  customsBrokerBlock: string;
  fscNote: string;
  usaTariffNote: string;
  companyFromAddress: string;
  paymentTerms: string;
  confirmWith: string;
  footerNotes: string;
  signatureNote: string;
}

// Lists are edited as one item per line; blank lines are dropped on save.
function toLines(items: string[]): string {
  return (items ?? []).join('\n');
}
function fromLines(text: string): string[] {
  return text.split('\n').map((l) => l.trim()).filter((l) => l.length > 0);
}

export default function PODocumentSettingsPage() {
  const { ownsTenant, hasRole } = useIdentity();
  const canEdit = ownsTenant || hasRole('PO Manager');
  const { data, loading, error } = useQuery<{ poDocumentSettings: PODocumentSettings }>(GET_PO_DOCUMENT_SETTINGS);

  return (
    <Box>
      {/* Outside the branches below: the PAGE HEADER names the way back in every state, including
          while the settings are still loading and when the role gate turns the page down. */}
      <PageHeader
        title="PO Document Settings"
        parent={{ label: 'Purchase Orders', to: '/app/po' }}
        description="Company-wide boilerplate printed on every generated supplier PO document. Per-PO fields (vendor address, ship-to, totals) are captured when generating."
        sx={{ maxWidth: 820, mb: 3 }}
      />
      {!canEdit ? (
        <Alert severity="warning">You need the PO Manager or Tenant Owner role to edit PO document settings.</Alert>
      ) : loading && !data ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
          <CircularProgress />
        </Box>
      ) : data ? (
        <SettingsForm settings={data.poDocumentSettings} />
      ) : (
        // #1279: a failed read used to leave the page blank under its header.
        <Alert severity="error">
          The PO document settings could not be loaded. {error?.message ?? 'Reload the page to try again.'}
        </Alert>
      )}
    </Box>
  );
}

function SettingsForm({ settings }: { settings: PODocumentSettings }) {
  const { showToast } = useToast();

  const [taxNumbers, setTaxNumbers] = useState(settings.taxNumbers);
  const [mandatoryBullets, setMandatoryBullets] = useState(toLines(settings.mandatoryBullets));
  const [shippingAccounts, setShippingAccounts] = useState(toLines(settings.shippingAccounts));
  const [customsBrokerBlock, setCustomsBrokerBlock] = useState(settings.customsBrokerBlock);
  const [fscNote, setFscNote] = useState(settings.fscNote);
  const [usaTariffNote, setUsaTariffNote] = useState(settings.usaTariffNote);
  const [paymentTerms, setPaymentTerms] = useState(settings.paymentTerms);
  const [confirmWith, setConfirmWith] = useState(settings.confirmWith);
  const [footerNotes, setFooterNotes] = useState(settings.footerNotes);
  const [signatureNote, setSignatureNote] = useState(settings.signatureNote);

  const [updateSettings, { loading: saving }] = useMutation(UPDATE_PO_DOCUMENT_SETTINGS, {
    onCompleted: () => showToast('PO document settings saved', 'success'),
    onError: (err) => showToast(userMessage(err), 'error'),
  });

  const handleSave = () => {
    updateSettings({
      variables: {
        input: {
          taxNumbers,
          mandatoryBullets: fromLines(mandatoryBullets),
          shippingAccounts: fromLines(shippingAccounts),
          customsBrokerBlock,
          fscNote,
          usaTariffNote,
          paymentTerms,
          confirmWith,
          footerNotes,
          signatureNote,
        },
      },
    });
  };

  return (
    <FadeIn>
    <Box sx={{ maxWidth: 820 }}>
      <Stack spacing={2.5}>
        <SectionHeading>Company &amp; terms</SectionHeading>
        <CompanyAddressSection />

        <Stack direction="row" spacing={2}>
          <TextField
            label="Payment terms" value={paymentTerms} onChange={(e) => setPaymentTerms(e.target.value)}
            fullWidth
          />
          <TextField
            label="Confirm with" value={confirmWith} onChange={(e) => setConfirmWith(e.target.value)}
            fullWidth
          />
        </Stack>

        <SectionHeading>Tax &amp; mandatory notes</SectionHeading>
        <TextField
          label="Tax numbers" value={taxNumbers} onChange={(e) => setTaxNumbers(e.target.value)}
          fullWidth multiline minRows={3} helperText="GST / PST / HST lines, one per line."
        />
        <TextField
          label="Mandatory bullets" value={mandatoryBullets} onChange={(e) => setMandatoryBullets(e.target.value)}
          fullWidth multiline minRows={4}
          helperText="One bullet per line. Printed below the totals on every PO."
        />

        <SectionHeading>Conditional notes</SectionHeading>
        <TextField
          label="Wood-door FSC note" value={fscNote} onChange={(e) => setFscNote(e.target.value)}
          fullWidth multiline minRows={2}
        />
        <TextField
          label="USA tariff note" value={usaTariffNote} onChange={(e) => setUsaTariffNote(e.target.value)}
          fullWidth multiline minRows={2}
        />

        <SectionHeading>Customs &amp; shipping accounts</SectionHeading>
        <TextField
          label="Customs broker block" value={customsBrokerBlock}
          onChange={(e) => setCustomsBrokerBlock(e.target.value)}
          fullWidth multiline minRows={4} helperText="Business number + broker details for international shipments."
        />
        <TextField
          label="Shipping accounts" value={shippingAccounts}
          onChange={(e) => setShippingAccounts(e.target.value)}
          fullWidth multiline minRows={3} helperText="Courier account lines, one per line."
        />

        <SectionHeading>Signature &amp; footer</SectionHeading>
        <TextField
          label="Signature note" value={signatureNote} onChange={(e) => setSignatureNote(e.target.value)}
          fullWidth
        />
        <TextField
          label="Footer notes" value={footerNotes} onChange={(e) => setFooterNotes(e.target.value)}
          fullWidth multiline minRows={2}
        />

        <Box>
          <Button variant="contained" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving...' : 'Save Settings'}
          </Button>
        </Box>
      </Stack>
    </Box>
    </FadeIn>
  );
}

/**
 * #1689: each GP company prints GP's name for itself and its own address (ruled on #1762). The name is
 * GP's and changes there; the address is set here, for the company the page is working in.
 */
function CompanyAddressSection() {
  // A scoped user's company is the one the server scopes them to; only an admin, who switches, names one.
  const { company, canSwitch } = useActingCompany();
  const { data, loading, error } = useQuery<{ companyLetterhead: CompanyLetterhead }>(GET_COMPANY_LETTERHEAD, {
    variables: { company: canSwitch ? company : null }, skip: !company,
  });
  if (!company) {
    return <Alert severity="info">Pick a company in the app bar to set the address it prints.</Alert>;
  }
  if (error) {
    return <Alert severity="error">The company's printed address could not be loaded. {userMessage(error, { reading: true })}</Alert>;
  }
  if (loading || !data) return <CircularProgress size={20} />;
  return <CompanyAddressForm key={company} letterhead={data.companyLetterhead} />;
}

function CompanyAddressForm({ letterhead }: { letterhead: CompanyLetterhead }) {
  const { showToast } = useToast();
  const [address, setAddress] = useState(letterhead.address);
  const [save, { loading: saving }] = useMutation(SET_COMPANY_ADDRESS, {
    onCompleted: () => showToast(`${letterhead.company}'s printed address saved`, 'success'),
    onError: (err) => showToast(userMessage(err), 'error'),
  });
  return (
    <Stack spacing={1.5}>
      <Stack direction="row" spacing={2} sx={{ alignItems: 'flex-start' }}>
        <TextField
          label="Printed name" value={letterhead.name} disabled
          helperText={`GP's name for ${letterhead.company}. It changes in GP.`}
          sx={{ flex: 2, minWidth: 0 }}
        />
        <TextField
          label={`${letterhead.company} address`} value={address}
          onChange={(e) => setAddress(e.target.value)}
          multiline minRows={2}
          helperText="Printed under the name, top-left of the PO and in the delivery request's Division Address box. One line each."
          sx={{ flex: 3, minWidth: 0 }}
        />
      </Stack>
      <Box>
        <Button
          variant="outlined" disabled={saving}
          onClick={() => save({ variables: { address, company: letterhead.company } })}
        >
          {saving ? 'Saving...' : 'Save address'}
        </Button>
      </Box>
    </Stack>
  );
}
