using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Data.Linq.Mapping;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Threading.Tasks;

namespace PM_Project_Tracking.DataClasses.UtilityClasses
{
    //http://stackoverflow.com/questions/2738494/how-to-i-define-change-the-mappings-for-linq-to-sql-in-code
    //http://pastebin.com/CxXUbT1n  <---the whole thing with the missing methods, use that

    public class OverrideMappingSource : MappingSource
    {
        private readonly MappingSource innerSource;
        private readonly List<TableOverride> tableOverrides = new List<TableOverride>();

        public OverrideMappingSource(MappingSource innerSource)
        {
            if (innerSource == null)
                throw new ArgumentNullException("innerSource");
            this.innerSource = innerSource;
        }

        protected override MetaModel CreateModel(Type dataContextType)
        {
            var innerModel = innerSource.GetModel(dataContextType);
            return new OverrideMetaModel(this, innerModel, tableOverrides);
        }

        public void OverrideTable(Type entityType, string tableName)
        {
            tableOverrides.Add(new TableOverride(entityType, tableName));
        }
    }

    public class OverrideMetaModel : MetaModel
    {
        private readonly MappingSource source;
        private readonly MetaModel innerModel;
        private readonly List<TableOverride> tableOverrides = new List<TableOverride>();

        public OverrideMetaModel(MappingSource source, MetaModel innerModel,
            IEnumerable<TableOverride> tableOverrides)
        {
            if (source == null)
                throw new ArgumentNullException("source");
            if (innerModel == null)
                throw new ArgumentNullException("innerModel");
            this.source = source;
            this.innerModel = innerModel;
            if (tableOverrides != null)
                this.tableOverrides.AddRange(tableOverrides);
        }

        public override Type ContextType
        {
            get { return innerModel.ContextType; }
        }

        public override string DatabaseName
        {
            get { return innerModel.DatabaseName; }
        }

        public override MetaFunction GetFunction(MethodInfo method)
        {
            return innerModel.GetFunction(method);
        }

        public override IEnumerable<MetaFunction> GetFunctions()
        {
            return innerModel.GetFunctions();
        }

        public override MetaType GetMetaType(Type type)
        {
            return Wrap(innerModel.GetMetaType(type));
        }

        public override MetaTable GetTable(Type rowType)
        {
            return Wrap(innerModel.GetTable(rowType));
        }

        public override IEnumerable<MetaTable> GetTables()
        {
            return innerModel.GetTables().Select(t => Wrap(t));
        }

        private MetaTable Wrap(MetaTable innerTable)
        {
            TableOverride ovr = tableOverrides.FirstOrDefault(o =>
                o.EntityType == innerTable.RowType.Type);
            return (ovr != null) ? new OverrideMetaTable(this, innerTable, ovr.TableName) : innerTable;
        }

        private MetaType Wrap(MetaType innerType)
        {
            TableOverride ovr = tableOverrides.FirstOrDefault(o =>
                o.EntityType == innerType.Type);
            return (ovr != null) ?
                new OverrideMetaType(this, innerType, Wrap(innerType.Table)) : innerType;
        }

        public override MappingSource MappingSource
        {
            get { return source; }
        }

        public override Type ProviderType
        {
            get { return innerModel.ProviderType; }
        }
    }

    public class OverrideMetaTable : MetaTable
    {
        private readonly MetaModel model;
        private readonly MetaTable innerTable;
        private readonly string tableName;

        public OverrideMetaTable(MetaModel model, MetaTable innerTable, string tableName)
        {
            if (model == null)
                throw new ArgumentNullException("model");
            if (innerTable == null)
                throw new ArgumentNullException("innerTable");
            if (string.IsNullOrEmpty(tableName))
                throw new ArgumentNullException("tableName");
            this.model = model;
            this.innerTable = innerTable;
            this.tableName = tableName;
        }

        public override MethodInfo DeleteMethod
        {
            get { return innerTable.DeleteMethod; }
        }

        public override MethodInfo InsertMethod
        {
            get { return innerTable.InsertMethod; }
        }

        public override MetaModel Model
        {
            get { return model; }
        }

        public override MetaType RowType
        {
            get { return new OverrideMetaType(model, innerTable.RowType, this); }
        }

        public override string TableName
        {
            get { return tableName; }
        }

        public override MethodInfo UpdateMethod
        {
            get { return innerTable.UpdateMethod; }
        }
    }

    public class OverrideMetaType : MetaType
    {
        private readonly MetaModel model;
        private readonly MetaType innerType;
        private readonly MetaTable overrideTable;

        public OverrideMetaType(MetaModel model, MetaType innerType, MetaTable overrideTable)
        {
            if (model == null)
                throw new ArgumentNullException("model");
            if (innerType == null)
                throw new ArgumentNullException("innerType");
            if (overrideTable == null)
                throw new ArgumentNullException("overrideTable");
            this.model = model;
            this.innerType = innerType;
            this.overrideTable = overrideTable;
        }

        public override ReadOnlyCollection<MetaAssociation> Associations
        {
            get { return innerType.Associations; }
        }

        public override bool CanInstantiate
        {
            get { return innerType.CanInstantiate; }
        }

        public override MetaDataMember DBGeneratedIdentityMember
        {
            get { return innerType.DBGeneratedIdentityMember; }
        }

        public override ReadOnlyCollection<MetaDataMember> DataMembers
        {
            get { return innerType.DataMembers; }
        }

        public override ReadOnlyCollection<MetaType> DerivedTypes
        {
            get { return innerType.DerivedTypes; }
        }

        public override MetaDataMember Discriminator
        {
            get { return innerType.Discriminator; }
        }

        public override MetaDataMember GetDataMember(MemberInfo member)
        {
            return innerType.GetDataMember(member);
        }

        public override MetaType GetInheritanceType(Type type)
        {
            return innerType.GetInheritanceType(type);
        }

        public override MetaType GetTypeForInheritanceCode(object code)
        {
            return innerType.GetTypeForInheritanceCode(code);
        }

        public override bool HasAnyLoadMethod
        {
            get { return innerType.HasAnyLoadMethod; }
        }

        public override bool HasAnyValidateMethod
        {
            get { return innerType.HasAnyValidateMethod; }
        }

        public override bool HasInheritance
        {
            get { return innerType.HasInheritance; }
        }

        public override bool HasInheritanceCode
        {
            get { return innerType.HasInheritanceCode; }
        }

        public override bool HasUpdateCheck
        {
            get { return innerType.HasUpdateCheck; }
        }

        public override ReadOnlyCollection<MetaDataMember> IdentityMembers
        {
            get { return innerType.IdentityMembers; }
        }

        public override MetaType InheritanceBase
        {
            get { return innerType.InheritanceBase; }
        }

        public override object InheritanceCode
        {
            get { return innerType.InheritanceCode; }
        }

        public override MetaType InheritanceDefault
        {
            get { return innerType.InheritanceDefault; }
        }

        public override MetaType InheritanceRoot
        {
            get { return innerType.InheritanceRoot; }
        }

        public override ReadOnlyCollection<MetaType> InheritanceTypes
        {
            get { return innerType.InheritanceTypes; }
        }

        public override bool IsEntity
        {
            get { return innerType.IsEntity; }
        }

        public override bool IsInheritanceDefault
        {
            get { return innerType.IsInheritanceDefault; }
        }

        public override MetaModel Model
        {
            get { return model; }
        }

        public override string Name
        {
            get { return innerType.Name; }
        }

        public override MethodInfo OnLoadedMethod
        {
            get { return innerType.OnLoadedMethod; }
        }

        public override MethodInfo OnValidateMethod
        {
            get { return innerType.OnValidateMethod; }
        }

        public override ReadOnlyCollection<MetaDataMember> PersistentDataMembers
        {
            get { return innerType.PersistentDataMembers; }
        }

        public override MetaTable Table
        {
            get { return overrideTable; }
        }

        public override Type Type
        {
            get { return innerType.Type; }
        }

        public override MetaDataMember VersionMember
        {
            get { return innerType.VersionMember; }
        }
    }

    public class TableOverride
    {
        public TableOverride(Type entityType, string tableName)
        {
            if (entityType == null)
                throw new ArgumentNullException("entityType");
            if (string.IsNullOrEmpty(tableName))
                throw new ArgumentNullException("tableName");
            this.EntityType = entityType;
            this.TableName = tableName;
        }

        public Type EntityType { get; private set; }
        public string TableName { get; private set; }
    }
}
