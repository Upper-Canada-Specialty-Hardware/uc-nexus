import { Box, Card, CardContent, Typography, Skeleton } from '@mui/material';
import type { ReactNode } from 'react';

export interface StatCardProps {
  icon: ReactNode;
  label: string;
  value: string | number;
  color?: string;
}

export function StatCard({ icon, label, value, color }: StatCardProps) {
  return (
    <Card variant="outlined" sx={{ flex: '1 1 0', minWidth: 140 }}>
      <CardContent sx={{ display: 'flex', alignItems: 'center', gap: 1.5, py: 1.5, '&:last-child': { pb: 1.5 } }}>
        <Box sx={{ color: color ?? 'text.secondary', display: 'flex' }}>{icon}</Box>
        <Box>
          <Typography variant="h6" sx={{ lineHeight: 1.2 }}>{value}</Typography>
          <Typography variant="caption" color="text.secondary">{label}</Typography>
        </Box>
      </CardContent>
    </Card>
  );
}

export function StatCardSkeleton() {
  return (
    <Card variant="outlined" sx={{ flex: '1 1 0', minWidth: 140 }}>
      <CardContent sx={{ py: 1.5, '&:last-child': { pb: 1.5 } }}>
        <Skeleton width={80} height={28} />
        <Skeleton width={60} height={16} />
      </CardContent>
    </Card>
  );
}
