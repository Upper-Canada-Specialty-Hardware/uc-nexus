import { useState, type ReactNode } from 'react';
import {
  Box, Typography, TextField, Button, Stack, Alert, CircularProgress,
} from '@mui/material';
import { useQuery, useMutation } from '@apollo/client/react';
import { GET_PO_DOCUMENT_SETTINGS, UPDATE_PO_DOCUMENT_SETTINGS } from '../../graphql/po';
import { useToast } from '../../components/Toast';
import { useIdentity } from '../../hooks/useIdentity';
import { microLabelSx } from '../../theme';
import { FadeIn } from '../../motion';

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
  shippingMethods: string[];
  customsBrokerBlock: string;
  fscNote: string;
  usaTariffNote: string;
  usaTariffEffectiveUntil: string | null;
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
  const { isAdmin } = useIdentity();
  const { data, loading } = useQuery<{ poDocumentSettings: PODocumentSettings }>(GET_PO_DOCUMENT_SETTINGS);

  return (
    <Box>
      {/* No back link: the nav rail's breadcrumb already says where this page sits. */}
      {!isAdmin ? (
        <Alert severity="warning">You need the Admin/Manager role to edit PO document settings.</Alert>
      ) : loading && !data ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
          <CircularProgress />
        </Box>
      ) : data ? (
        <SettingsForm settings={data.poDocumentSettings} />
      ) : null}
    </Box>
  );
}

function SettingsForm({ settings }: { settings: PODocumentSettings }) {
  const { showToast } = useToast();

  const [taxNumbers, setTaxNumbers] = useState(settings.taxNumbers);
  const [mandatoryBullets, setMandatoryBullets] = useState(toLines(settings.mandatoryBullets));
  const [shippingAccounts, setShippingAccounts] = useState(toLines(settings.shippingAccounts));
  const [shippingMethods, setShippingMethods] = useState(toLines(settings.shippingMethods));
  const [customsBrokerBlock, setCustomsBrokerBlock] = useState(settings.customsBrokerBlock);
  const [fscNote, setFscNote] = useState(settings.fscNote);
  const [usaTariffNote, setUsaTariffNote] = useState(settings.usaTariffNote);
  const [usaTariffEffectiveUntil, setUsaTariffEffectiveUntil] = useState(settings.usaTariffEffectiveUntil ?? '');
  const [companyFromAddress, setCompanyFromAddress] = useState(settings.companyFromAddress);
  const [paymentTerms, setPaymentTerms] = useState(settings.paymentTerms);
  const [confirmWith, setConfirmWith] = useState(settings.confirmWith);
  const [footerNotes, setFooterNotes] = useState(settings.footerNotes);
  const [signatureNote, setSignatureNote] = useState(settings.signatureNote);

  const [updateSettings, { loading: saving }] = useMutation(UPDATE_PO_DOCUMENT_SETTINGS, {
    onCompleted: () => showToast('PO document settings saved', 'success'),
    onError: (err) => showToast(err.message, 'error'),
  });

  const handleSave = () => {
    updateSettings({
      variables: {
        input: {
          taxNumbers,
          mandatoryBullets: fromLines(mandatoryBullets),
          shippingAccounts: fromLines(shippingAccounts),
          shippingMethods: fromLines(shippingMethods),
          customsBrokerBlock,
          fscNote,
          usaTariffNote,
          usaTariffEffectiveUntil: usaTariffEffectiveUntil || null,
          companyFromAddress,
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
      <Typography variant="h5" gutterBottom>PO Document Settings</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Company-wide boilerplate printed on every generated supplier PO document. Per-PO fields
        (vendor address, ship-to, totals) are captured when generating.
      </Typography>

      <Stack spacing={2.5}>
        <SectionHeading>Company &amp; terms</SectionHeading>
        <TextField
          label="Company from-address" value={companyFromAddress}
          onChange={(e) => setCompanyFromAddress(e.target.value)}
          fullWidth multiline minRows={3} helperText="Printed top-left of the document, one line each."
        />

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
        <TextField
          label="Shipping methods" value={shippingMethods}
          onChange={(e) => setShippingMethods(e.target.value)}
          fullWidth multiline minRows={3}
          helperText="Dropdown options for the generate dialog's Shipping Method, one per line."
        />

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
        <TextField
          label="USA tariff note effective until" type="date" value={usaTariffEffectiveUntil}
          onChange={(e) => setUsaTariffEffectiveUntil(e.target.value)}
          slotProps={{ inputLabel: { shrink: true } }}
          helperText="Shown to the PO user next to the tariff toggle. Clear to remove the date."
          sx={{ maxWidth: 280 }}
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
