from __future__ import nested_scopes
from types import ListType, TupleType, StringType
from Products.Archetypes.Storage import MetadataStorage
from Products.Archetypes.Layer import DefaultLayerContainer
from Products.Archetypes.interfaces.field import IField
from Products.Archetypes.interfaces.layer import ILayerContainer, \
     ILayerRuntime, ILayer
from Products.Archetypes.interfaces.storage import IStorage
from Products.Archetypes.interfaces.schema import ISchema, ISchemata, \
     IManagedSchema
from Products.Archetypes.utils import OrderedDict, mapply, shasattr
from Products.Archetypes.debug import log, warn
from Products.Archetypes.exceptions import SchemaException
from Products.Archetypes.exceptions import ReferenceException

from AccessControl import ClassSecurityInfo
from Acquisition import aq_base, Explicit
from ExtensionClass import Base
from Globals import InitializeClass
from Products.CMFCore import CMFCorePermissions

__docformat__ = 'reStructuredText'

def getNames(schema):
    """Returns a list of all fieldnames in the given schema."""
    return [f.getName() for f in schema.fields()]

def getSchemata(obj):
    """Returns an ordered dictionary, which maps all Schemata names to fields
    that belong to the Schemata."""

    schema = obj.Schema()
    schemata = OrderedDict()
    for f in schema.fields():
        sub = schemata.get(f.schemata, WrappedSchemata(name=f.schemata))
        sub.addField(f)
        schemata[f.schemata] = sub.__of__(obj)

    return schemata

class Schemata(Base):
    """Manage a list of fields by grouping them together.

    Schematas are identified by their names.
    """

    security = ClassSecurityInfo()
    security.setDefaultAccess('allow')

    __implements__ = ISchemata

    def __init__(self, name='default', fields=None):
        """Initialize Schemata and add optional fields."""

        self.__name__ = name
        self._names = []
        self._fields = {}

        if fields is not None:
            if type(fields) not in [ListType, TupleType]:
                fields = (fields, )

            for field in fields:
                self.addField(field)

    security.declareProtected(CMFCorePermissions.View, 'getName')
    def getName(self):
        """Returns the Schemata's name."""
        return self.__name__


    def __add__(self, other):
        """Returns a new Schemata object that contains all fields and layers
        from ``self`` and ``other``.
        """

        c = Schemata()
        for field in self.fields():
            c.addField(field)
        for field in other.fields():
            c.addField(field)

        return c


    security.declareProtected(CMFCorePermissions.View, 'copy')
    def copy(self):
        """Returns a deep copy of this Schemata.
        """
        c = Schemata()
        for field in self.fields():
            c.addField(field.copy())
        return c


    security.declareProtected(CMFCorePermissions.View, 'fields')
    def fields(self):
        """Returns a list of my fields in order of their indices."""
        return [self._fields[name] for name in self._names]


    security.declareProtected(CMFCorePermissions.View, 'values')
    values = fields

    security.declareProtected(CMFCorePermissions.View, 'editableFields')
    def editableFields(self, instance, visible_only=False):
        """Returns a list of editable fields for the given instance
        """
        ret = []
        for field in self.fields():
            if field.writeable(instance, debug=False):
                if not visible_only:
                    ret.append(field)
                else:
                    visible = True
                    if hasattr(field.widget, 'visible') and \
                       field.widget.visible.get('edit', 'visible') != 'visible':
                        visible = False
                    if visible:
                        ret.append(field)
        return ret

    security.declareProtected(CMFCorePermissions.View, 'viewableFields')
    def viewableFields(self, instance):
        """Returns a list of viewable fields for the given instance
        """
        return [field for field in self.fields()
                if field.checkPermission('view', instance)]

    security.declareProtected(CMFCorePermissions.View, 'widgets')
    def widgets(self):
        """Returns a dictionary that contains a widget for
        each field, using the field name as key."""

        widgets = {}
        for f in self.fields():
            widgets[f.getName()] = f.widget
        return widgets

    security.declareProtected(CMFCorePermissions.View,
                              'filterFields')
    def filterFields(self, *predicates, **values):
        """Returns a subset of self.fields(), containing only fields that
        satisfy the given conditions.

        You can either specify predicates or values or both. If you provide
        both, all conditions must be satisfied.

        For each ``predicate`` (positional argument), ``predicate(field)`` must
        return 1 for a Field ``field`` to be returned as part of the result.

        Each ``attr=val`` function argument defines an additional predicate:
        A field must have the attribute ``attr`` and field.attr must be equal
        to value ``val`` for it to be in the returned list.
        """

        results = []

        for field in self.fields(): # step through each of my fields

            # predicate failed:
            failed = [pred for pred in predicates if not pred(field)]
            if failed: continue

            # attribute missing:
            missing_attrs = [attr for attr in values.keys() \
                             if not shasattr(field, attr)]
            if missing_attrs: continue

            # attribute value unequal:
            diff_values = [attr for attr in values.keys() \
                           if getattr(field, attr) != values[attr]]
            if diff_values: continue

            results.append(field)

        return results

    def __setitem__(self, name, field):
        assert name == field.getName()
        self.addField(field)

    security.declareProtected(CMFCorePermissions.ModifyPortalContent,
                              'addField')
    def addField(self, field):
        """Adds a given field to my dictionary of fields."""
        field = aq_base(field)
        self._validateOnAdd(field)
        name = field.getName()
        if name not in self._names:
            self._names.append(name)
        self._fields[name] = field

    def _validateOnAdd(self, field):
        """Validates fields on adding and bootstrapping
        """
        # interface test
        if not IField.isImplementedBy(field):
            raise ValueError, "Object doesn't implement IField: %r" % field
        name = field.getName()
        # two primary fields are forbidden
        if getattr(field, 'primary', False):
            res = self.hasPrimary()
            if res is not False and name != res.getName():
                raise SchemaException("Tried to add '%s' as primary field "\
                         "but %s already has the primary field '%s'." % \
                         (name, repr(self), res.getName())
                      )
        # Do not allowed unqualified references
        if field.type in ('reference', ):
            relationship = getattr(field, 'relationship', '')
            if type(relationship) is not StringType or len(relationship) == 0:
                raise ReferenceException("Unqualified relationship or "\
                          "unsupported relationship var type in field '%s'. "\
                          "The relationship qualifer must be a non empty "\
                          "string." % name
                      )


    def __delitem__(self, name):
        if not self._fields.has_key(name):
            raise KeyError("Schemata has no field '%s'" % name)
        del self._fields[name]
        self._names.remove(name)

    def __getitem__(self, name):
        return self._fields[name]

    security.declareProtected(CMFCorePermissions.View, 'get')
    def get(self, name, default=None):
        return self._fields.get(name, default)

    security.declareProtected(CMFCorePermissions.View, 'has_key')
    def has_key(self, name):
        return self._fields.has_key(name)

    security.declareProtected(CMFCorePermissions.View, 'keys')
    def keys(self):
        return self._names

    security.declareProtected(CMFCorePermissions.ModifyPortalContent,
                              'delField')
    delField = __delitem__

    security.declareProtected(CMFCorePermissions.ModifyPortalContent,
                              'updateField')
    updateField = addField

    security.declareProtected(CMFCorePermissions.View, 'searchable')
    def searchable(self):
        """Returns a list containing names of all searchable fields."""

        return [f.getName() for f in self.fields() if f.searchable]

    def hasPrimary(self):
        """Returns the first primary field or False"""
        for f in self.fields():
            if getattr(f, 'primary', False):
                return f
        return False

InitializeClass(Schemata)


class WrappedSchemata(Schemata, Explicit):
    """
    Wrapped Schemata
    """

    security = ClassSecurityInfo()
    security.setDefaultAccess('allow')

InitializeClass(WrappedSchemata)


class SchemaLayerContainer(DefaultLayerContainer):
    """Some layer management for schemas"""

    security = ClassSecurityInfo()
    security.setDefaultAccess('allow')

    _properties = {
        'marshall' : None
        }

    def __init__(self):
        DefaultLayerContainer.__init__(self)
        #Layer init work
        marshall = self._props.get('marshall')
        if marshall:
            self.registerLayer('marshall', marshall)

    # ILayerRuntime
    security.declareProtected(CMFCorePermissions.ModifyPortalContent,
                              'initializeLayers')
    def initializeLayers(self, instance, item=None, container=None):
        # scan each field looking for registered layers optionally
        # call its initializeInstance method and then the
        # initializeField method
        initializedLayers = []
        called = lambda x: x in initializedLayers

        for field in self.fields():
            if ILayerContainer.isImplementedBy(field):
                layers = field.registeredLayers()
                for layer, obj in layers:
                    if ILayer.isImplementedBy(obj):
                        if not called((layer, obj)):
                            obj.initializeInstance(instance, item, container)
                            # Some layers may have the same name, but
                            # different classes, so, they may still
                            # need to be initialized
                            initializedLayers.append((layer, obj))
                        obj.initializeField(instance, field)

        # Now do the same for objects registered at this level
        if ILayerContainer.isImplementedBy(self):
            for layer, obj in self.registeredLayers():
                if (not called((layer, obj)) and
                    ILayer.isImplementedBy(obj)):
                    obj.initializeInstance(instance, item, container)
                    initializedLayers.append((layer, obj))


    security.declareProtected(CMFCorePermissions.ModifyPortalContent,
                              'cleanupLayers')
    def cleanupLayers(self, instance, item=None, container=None):
        # scan each field looking for registered layers optionally
        # call its cleanupInstance method and then the cleanupField
        # method
        queuedLayers = []
        queued = lambda x: x in queuedLayers

        for field in self.fields():
            if ILayerContainer.isImplementedBy(field):
                layers = field.registeredLayers()
                for layer, obj in layers:
                    if not queued((layer, obj)):
                        queuedLayers.append((layer, obj))
                    if ILayer.isImplementedBy(obj):
                        obj.cleanupField(instance, field)

        for layer, obj in queuedLayers:
            if ILayer.isImplementedBy(obj):
                obj.cleanupInstance(instance, item, container)

        # Now do the same for objects registered at this level

        if ILayerContainer.isImplementedBy(self):
            for layer, obj in self.registeredLayers():
                if (not queued((layer, obj)) and
                    ILayer.isImplementedBy(obj)):
                    obj.cleanupInstance(instance, item, container)
                    queuedLayers.append((layer, obj))

    def __add__(self, other):
        c = SchemaLayerContainer()
        layers = {}
        for k, v in self.registeredLayers():
            layers[k] = v
        for k, v in other.registeredLayers():
            layers[k] = v
        for k, v in layers.items():
            c.registerLayer(k, v)
        return c

    security.declareProtected(CMFCorePermissions.View, 'copy')
    def copy(self):
        c = SchemaLayerContainer()
        layers = {}
        for k, v in self.registeredLayers():
            c.registerLayer(k, v)
        return c

InitializeClass(SchemaLayerContainer)


class BasicSchema(Schemata):
    """Manage a list of fields and run methods over them."""

    __implements__ = ISchema

    security = ClassSecurityInfo()
    security.setDefaultAccess('allow')

    _properties = {}

    def __init__(self, *args, **kwargs):
        """
        Initialize a Schema.

        The first positional argument may be a sequence of
        Fields. (All further positional arguments are ignored.)

        Keyword arguments are added to my properties.
        """
        Schemata.__init__(self)

        self._props = self._properties.copy()
        self._props.update(kwargs)

        if len(args):
            if type(args[0]) in [ListType, TupleType]:
                for field in args[0]:
                    self.addField(field)
            else:
                msg = ('You are passing positional arguments '
                       'to the Schema constructor. '
                       'Please consult the docstring '
                       'for %s.BasicSchema.__init__' %
                       (self.__class__.__module__,))
                level = 3
                if self.__class__ is not BasicSchema:
                    level = 4
                warn(msg, level=level)
                for field in args:
                    self.addField(args[0])

    def __add__(self, other):
        c = BasicSchema()
        # We can't use update and keep the order so we do it manually
        for field in self.fields():
            c.addField(field)
        for field in other.fields():
            c.addField(field)
        # Need to be smarter when joining layers
        # and internal props
        c._props.update(self._props)
        return c

    security.declareProtected(CMFCorePermissions.View, 'copy')
    def copy(self):
        """Returns a deep copy of this Schema.
        """
        c = BasicSchema()
        for field in self.fields():
            c.addField(field.copy())
        # Need to be smarter when joining layers
        # and internal props
        c._props.update(self._props)
        return c

    security.declareProtected(CMFCorePermissions.ModifyPortalContent, 'edit')
    def edit(self, instance, name, value):
        if self.allow(name):
            instance[name] = value

    security.declareProtected(CMFCorePermissions.ModifyPortalContent,
                              'setDefaults')
    def setDefaults(self, instance):
        """Only call during object initialization. Sets fields to
        schema defaults
        """
        ## XXX think about layout/vs dyn defaults
        for field in self.values():
            if field.getName().lower() == 'id': continue
            if field.type == "reference": continue

            # always set defaults on writable fields
            mutator = field.getMutator(instance)
            if mutator is None:
                continue
            default = field.getDefault(instance)

            args = (default,)
            kw = {'field': field.__name__}
            if shasattr(field, 'default_content_type'):
                # specify a mimetype if the mutator takes a
                # mimetype argument
                kw['mimetype'] = field.default_content_type
            mapply(mutator, *args, **kw)

    security.declareProtected(CMFCorePermissions.ModifyPortalContent,
                              'updateAll')
    def updateAll(self, instance, **kwargs):
        """This method mutates fields in the given instance.

        For each keyword argument k, the key indicates the name of the
        field to mutate while the value is used to call the mutator.

        E.g. updateAll(instance, id='123', amount=500) will, depending on the
        actual mutators set, result in two calls: ``instance.setId('123')`` and
        ``instance.setAmount(500)``.
        """

        keys = kwargs.keys()

        for field in self.values():
            if field.getName() not in keys:
                continue

            if not field.writeable(instance):
                continue

            # If passed the test above, mutator is guaranteed to
            # exist.
            method = field.getMutator(instance)
            method(kwargs[field.getName()])

    security.declareProtected(CMFCorePermissions.View, 'allow')
    def allow(self, name):
        return self.has_key(name)

    security.declareProtected(CMFCorePermissions.View, 'validate')
    def validate(self, instance=None, REQUEST=None,
                 errors=None, data=None, metadata=None):
        """Validate the state of the entire object.

        The passed dictionary ``errors`` will be filled with human readable
        error messages as values and the corresponding fields' names as
        keys.

        If a REQUEST object is present, validate the field values in the
        REQUEST.  Otherwise, validate the values currently in the object.
        """
        if REQUEST:
            fieldset = REQUEST.form.get('fieldset', None)
        else:
            fieldset = None
        fields = []

        if fieldset is not None:
            schemata = instance.Schemata()
            fields = [(field.getName(), field)
                      for field in schemata[fieldset].fields()]
        else:
            if data:
                fields.extend([(field.getName(), field)
                               for field in self.filterFields(isMetadata=0)])
            if metadata:
                fields.extend([(field.getName(), field)
                               for field in self.filterFields(isMetadata=1)])

        if REQUEST:
            form = REQUEST.form
        else:
            form = None
        _marker = []
        for name, field in fields:
            error = 0
            value = None
            widget = field.widget
            if form:
                result = widget.process_form(instance, field, form,
                                             empty_marker=_marker)
            else:
                result = None
            if result is None or result is _marker:
                accessor = field.getEditAccessor(instance) or field.getAccessor(instance)
                if accessor is not None:
                    value = accessor()
                else:
                    # can't get value to validate -- bail
                    continue
            else:
                value = result[0]

            res = field.validate(instance=instance,
                                 value=value,
                                 errors=errors,
                                 REQUEST=REQUEST)
            if res:
                errors[field.getName()] = res
        return errors


    # Utility method for converting a Schema to a string for the
    # purpose of comparing schema.  This comparison is used for
    # determining whether a schema has changed in the auto update
    # function.  Right now it's pretty crude.
    # XXX FIXME!
    security.declareProtected(CMFCorePermissions.View,
                              'toString')
    def toString(self):
        s = '%s: {' % self.__class__.__name__
        for f in self.fields():
            s = s + '%s,' % (f.toString())
        s = s + '}'
        return s

    security.declareProtected(CMFCorePermissions.View,
                              'signature')
    def signature(self):
        from md5 import md5
        return md5(self.toString()).digest()

    security.declareProtected(CMFCorePermissions.ModifyPortalContent,
                              'changeSchemataForField')
    def changeSchemataForField(self, fieldname, schemataname):
        """ change the schemata for a field """
        field = self[fieldname]
        self.delField(fieldname)
        field.schemata = schemataname
        self.addField(field)

    security.declareProtected(CMFCorePermissions.View, 'getSchemataNames')
    def getSchemataNames(self):
        """Return list of schemata names in order of appearing"""
        lst = []
        for f in self.fields():
            if not f.schemata in lst:
                lst.append(f.schemata)
        return lst

    security.declareProtected(CMFCorePermissions.View, 'getSchemataFields')
    def getSchemataFields(self, name):
        """Return list of fields belong to schema 'name'
        in order of appearing
        """
        return [f for f in self.fields() if f.schemata == name]

    security.declareProtected(CMFCorePermissions.ModifyPortalContent,
                              'replaceField')
    def replaceField(self, name, field):
        if IField.isImplementedBy(field):
            oidx = self._names.index(name)
            new_name = field.getName()
            self._names[oidx] = new_name
            del self._fields[name]
            self._fields[new_name] = field
        else:
            raise ValueError, "Object doesn't implement IField: %r" % field

InitializeClass(BasicSchema)


class Schema(BasicSchema, SchemaLayerContainer):
    """
    Schema
    """

    __implements__ = ILayerRuntime, ILayerContainer, ISchema

    security = ClassSecurityInfo()
    security.setDefaultAccess('allow')

    def __init__(self, *args, **kwargs):
        BasicSchema.__init__(self, *args, **kwargs)
        SchemaLayerContainer.__init__(self)

    def __add__(self, other):
        c = Schema()
        # We can't use update and keep the order so we do it manually
        for field in self.fields():
            c.addField(field)
        for field in other.fields():
            c.addField(field)
        # Need to be smarter when joining layers
        # and internal props
        c._props.update(self._props)
        layers = {}
        for k, v in self.registeredLayers():
            layers[k] = v
        for k, v in other.registeredLayers():
            layers[k] = v
        for k, v in layers.items():
            c.registerLayer(k, v)
        return c

    security.declareProtected(CMFCorePermissions.View, 'copy')
    def copy(self, factory=None):
        """Returns a deep copy of this Schema.
        """
        if factory is None:
            factory = self.__class__
        c = factory()
        for field in self.fields():
            c.addField(field.copy())
        # Need to be smarter when joining layers
        # and internal props
        c._props.update(self._props)
        layers = {}
        for k, v in self.registeredLayers():
            c.registerLayer(k, v)
        return c

    security.declareProtected(CMFCorePermissions.View, 'wrapped')
    def wrapped(self, parent):
        schema = self.copy(factory=WrappedSchema)
        return schema.__of__(parent)

InitializeClass(Schema)


class WrappedSchema(Schema, Explicit):
    """
    Wrapped Schema
    """

    security = ClassSecurityInfo()
    security.setDefaultAccess('allow')

InitializeClass(WrappedSchema)


class ManagedSchema(Schema):
    """
    Managed Schema
    """

    security = ClassSecurityInfo()
    security.setDefaultAccess('allow')

    __implements__ = IManagedSchema, Schema.__implements__

    security.declareProtected(CMFCorePermissions.ModifyPortalContent,
                              'delSchemata')
    def delSchemata(self, name):
        """Remove all fields belonging to schemata 'name'"""
        for f in self.fields():
            if f.schemata == name:
                self.delField(f.getName())

    security.declareProtected(CMFCorePermissions.ModifyPortalContent,
                              'addSchemata')
    def addSchemata(self, name):
        """Create a new schema by adding a new field with schemata 'name' """
        from Products.Archetypes.Field import StringField

        if name in self.getSchemataNames():
            raise ValueError, "Schemata '%s' already exists" % name
        self.addField(StringField('%s_default' % name, schemata=name))

    security.declareProtected(CMFCorePermissions.ModifyPortalContent,
                              'moveSchemata')
    def moveSchemata(self, name, direction):
        """Move a schemata to left (direction=-1) or to right
        (direction=1)
        """
        if not direction in (-1, 1):
            raise ValueError, 'Direction must be either -1 or 1'

        fields = self.fields()
        fieldnames = [f.getName() for f in fields]
        schemata_names = self.getSchemataNames()

        d = {}
        for s_name in self.getSchemataNames():
            d[s_name] = self.getSchemataFields(s_name)

        pos = schemata_names.index(name)
        if direction == -1:
            if pos > 0:
                schemata_names.remove(name)
                schemata_names.insert(pos-1, name)
        if direction == 1:
            if pos < len(schemata_names):
                schemata_names.remove(name)
                schemata_names.insert(pos+1, name)

        # remove and re-add
        self.__init__()

        for s_name in schemata_names:
            for f in fields:
                if f.schemata == s_name:
                    self.addField(f)

    security.declareProtected(CMFCorePermissions.ModifyPortalContent,
                              'moveField')
    def moveField(self, name, direction):
        """Move a field inside a schema to left
        (direction=-1) or to right (direction=1)
        """
        if not direction in (-1, 1):
            raise ValueError, "Direction must be either -1 or 1"

        fields = self.fields()
        fieldnames = [f.getName() for f in fields]
        schemata_names = self.getSchemataNames()

        field = self[name]
        field_schemata_name = self[name].schemata

        d = {}
        for s_name in self.getSchemataNames():
            d[s_name] = self.getSchemataFields(s_name)

        lst = d[field_schemata_name]  # list of fields of schemata
        pos = [f.getName() for f in lst].index(field.getName())

        if direction == -1:
            if pos > 0:
                del lst[pos]
                lst.insert(pos-1, field)
        if direction == 1:
            if pos < len(lst):
                del lst[pos]
                lst.insert(pos+1, field)

        d[field_schemata_name] = lst

        # remove and re-add
        self.__init__()
        for s_name in schemata_names:
            for f in d[s_name]:
                self.addField(f)

InitializeClass(ManagedSchema)


# Reusable instance for MetadataFieldList
MDS = MetadataStorage()

class MetadataSchema(Schema):
    """Schema that enforces MetadataStorage."""

    security = ClassSecurityInfo()
    security.setDefaultAccess('allow')

    security.declareProtected(CMFCorePermissions.ModifyPortalContent,
                              'addField')
    def addField(self, field):
        """Strictly enforce the contract that metadata is stored w/o
        markup and make sure each field is marked as such for
        generation and introspcection purposes.
        """
        _properties = {'isMetadata': 1,
                       'storage': MetadataStorage(),
                       'schemata': 'metadata',
                       'generateMode': 'mVc'}

        field.__dict__.update(_properties)
        field.registerLayer('storage', field.storage)

        Schema.addField(self, field)

InitializeClass(MetadataSchema)


FieldList = Schema
MetadataFieldList = MetadataSchema
