import { useMemo, useState, useCallback } from 'react';
import {
  Box,
  Paper,
  Typography,
  Table,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  Checkbox,
  Button,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Stack,
  Chip,
  type SelectChangeEvent,
} from '@mui/material';
import { useQuery, useMutation } from '@apollo/client/react';
import {
  GET_ASSEMBLE_LIST,
  GET_SHOP_ASSEMBLY_MEMBERS,
  ASSIGN_OPENINGS,
} from '../../graphql/shop-assembly';
import { leafSuffix } from '../../utils/leaf';
import { useToast } from '../../components/Toast';
import { isAvailableForAssignment } from './openingFilters';

interface AssembleOpening {
  id: string;
  openingId: string;
  pullStatus: string;
  assignedToUserId: string | null;
  assignedTo: string | null;
  assemblyStatus: string;
  openingNumber: string | null;
  building: string | null;
  floor: string | null;
  leaf: number | null;
  items: { id: string }[];
}

interface Member {
  id: string;
  firstName: string;
  lastName: string;
  email: string;
  roles: string[];
  imageUrl: string;
}

/** Display name for a member: full name, falling back to email (mirrors useIdentity()). */
function memberName(m: Member): string {
  return `${m.firstName} ${m.lastName}`.trim() || m.email;
}

/**
 * Manager-only tool (#330) to assign one or more pulled openings to a shop-assembly team member.
 * Mounted above the self-claim board; gated to the Shop Assembly Manager role at the mount site.
 */
export default function ManagerAssignPanel() {
  const { showToast } = useToast();
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [memberId, setMemberId] = useState('');

  // Shares the GET_ASSEMBLE_LIST cache with the board (same query + vars), so a refetch here keeps
  // both views in sync.
  const { data: listData, refetch } = useQuery<{ assembleList: AssembleOpening[] }>(GET_ASSEMBLE_LIST);
  const { data: memberData } = useQuery<{ shopAssemblyMembers: Member[] }>(GET_SHOP_ASSEMBLY_MEMBERS);

  const openings = listData?.assembleList ?? [];
  const members = memberData?.shopAssemblyMembers ?? [];

  const available = useMemo(() => openings.filter(isAvailableForAssignment), [openings]);

  // Current load per member: pending pulled openings already assigned to someone.
  const loadByMember = useMemo(() => {
    const counts = new Map<string, { id: string; name: string; count: number }>();
    for (const o of openings) {
      if (o.pullStatus === 'PULLED' && o.assemblyStatus === 'PENDING' && o.assignedToUserId) {
        const id = o.assignedToUserId;
        const prev = counts.get(id);
        counts.set(id, {
          id,
          name: o.assignedTo || prev?.name || id,
          count: (prev?.count ?? 0) + 1,
        });
      }
    }
    return [...counts.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [openings]);

  const [assignOpenings, { loading: assigning }] = useMutation(ASSIGN_OPENINGS, {
    onCompleted: (data) => {
      const count = (data as { assignOpenings: unknown[] }).assignOpenings.length;
      const member = members.find((m) => m.id === memberId);
      showToast(`${count} opening(s) assigned to ${member ? memberName(member) : 'member'}`, 'success');
      setSelectedIds(new Set());
      refetch();
    },
    onError: (err) => {
      showToast(err.message, 'error');
      refetch();
    },
  });

  const toggleOne = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const allSelected = available.length > 0 && selectedIds.size === available.length;
  const someSelected = selectedIds.size > 0 && !allSelected;

  const toggleAll = useCallback(() => {
    setSelectedIds((prev) =>
      prev.size === available.length ? new Set() : new Set(available.map((o) => o.id))
    );
  }, [available]);

  const handleMemberChange = useCallback((e: SelectChangeEvent) => setMemberId(e.target.value), []);

  const handleAssign = useCallback(() => {
    const member = members.find((m) => m.id === memberId);
    if (!member) {
      showToast('Pick a team member to assign to', 'error');
      return;
    }
    if (selectedIds.size === 0) {
      showToast('Select at least one opening', 'error');
      return;
    }
    assignOpenings({
      variables: {
        input: {
          openingIds: [...selectedIds],
          assignedToUserId: member.id,
          assignedTo: memberName(member),
        },
      },
    });
  }, [members, memberId, selectedIds, assignOpenings, showToast]);

  const selectedMember = members.find((m) => m.id === memberId);

  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
      <Typography variant="h6" gutterBottom>
        Assign to Team Member
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Select pulled openings and assign them to a shop-assembly team member. Assigned work shows up
        in that member's My Work.
      </Typography>

      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems={{ sm: 'center' }} sx={{ mb: 2 }}>
        <FormControl size="small" sx={{ minWidth: 240 }}>
          <InputLabel id="assign-member-label">Team member</InputLabel>
          <Select
            labelId="assign-member-label"
            label="Team member"
            value={memberId}
            onChange={handleMemberChange}
          >
            {members.length === 0 && (
              <MenuItem value="" disabled>
                No shop-assembly members found
              </MenuItem>
            )}
            {members.map((m) => (
              <MenuItem key={m.id} value={m.id}>
                {memberName(m)}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <Button
          variant="contained"
          disabled={assigning || selectedIds.size === 0 || !memberId}
          onClick={handleAssign}
        >
          {`Assign ${selectedIds.size || ''} ${selectedMember ? `to ${memberName(selectedMember)}` : 'selected'}`.replace(
            /\s+/g,
            ' '
          )}
        </Button>
      </Stack>

      {loadByMember.length > 0 && (
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 2 }}>
          <Typography variant="caption" color="text.secondary" sx={{ alignSelf: 'center' }}>
            Current load:
          </Typography>
          {loadByMember.map((l) => (
            <Chip key={l.id} size="small" variant="outlined" label={`${l.name}: ${l.count}`} />
          ))}
        </Stack>
      )}

      {available.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No unassigned pulled openings available.
        </Typography>
      ) : (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell padding="checkbox">
                <Checkbox
                  indeterminate={someSelected}
                  checked={allSelected}
                  onChange={toggleAll}
                  inputProps={{ 'aria-label': 'select all openings' }}
                />
              </TableCell>
              <TableCell>Opening</TableCell>
              <TableCell>Location</TableCell>
              <TableCell align="right">Items</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {available.map((o) => {
              const label = (o.openingNumber || o.openingId.slice(0, 8)) + leafSuffix(o.leaf);
              return (
                <TableRow key={o.id} hover onClick={() => toggleOne(o.id)} sx={{ cursor: 'pointer' }}>
                  <TableCell padding="checkbox">
                    <Checkbox
                      checked={selectedIds.has(o.id)}
                      onChange={() => toggleOne(o.id)}
                      onClick={(e) => e.stopPropagation()}
                      inputProps={{ 'aria-label': `select ${label}` }}
                    />
                  </TableCell>
                  <TableCell>{label}</TableCell>
                  <TableCell>
                    {[o.building, o.floor].filter(Boolean).join(' / ') || (
                      <Box component="span" sx={{ color: 'text.disabled' }}>
                        -
                      </Box>
                    )}
                  </TableCell>
                  <TableCell align="right">{o.items.length}</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
    </Paper>
  );
}
