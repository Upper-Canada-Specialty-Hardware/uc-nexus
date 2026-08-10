import HardwareItemsFlatTable from './HardwareItemsFlatTable';

interface HardwareItemsTabProps {
  projectId?: string;
}

/**
 * Warehouse inventory, Hardware Items tab.
 *
 * #506 replaced the category -> product-code -> location accordion with a flat table. The accordion
 * grouped by hardware category (or vendor) and hid every actual inventory line two levels down,
 * which meant the warehouse could not sort, filter or export across products - the questions it
 * actually asks. Grouping is now a sort or a filter on the table, and By Vendor is the Vendor
 * column. The Opening Items tab is unchanged.
 */
export default function HardwareItemsTab({ projectId }: HardwareItemsTabProps) {
  return <HardwareItemsFlatTable projectId={projectId} />;
}
