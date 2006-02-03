import os
import sys
from types import StringType, UnicodeType
import time
import urllib

from zope.deprecation import deprecated
from zope.interface import implements
from zope.component import getUtility

from archetypes.uid.interfaces import IUID
from archetypes.uid.interfaces import IUIDQuery
from archetypes.reference.interfaces import IReference as INewstyleReference
from archetypes.reference.interfaces import IReferenceQuery
from archetypes.reference.interfaces import IReferenceSource
from archetypes.reference.interfaces import IReferenceMetadata
from archetypes.reference.interfaces import IReferenceMetadataSetter

from Products.Archetypes.debug import log, log_exc
from Products.Archetypes.interfaces.referenceable import IReferenceable
from Products.Archetypes.interfaces.referenceengine import \
    IReference, IContentReference, IReferenceCatalog

from Products.Archetypes.utils import unique, make_uuid, getRelURL, \
    getRelPath, shasattr
from Products.Archetypes.config import UID_CATALOG, \
     REFERENCE_CATALOG,UUID_ATTR, REFERENCE_ANNOTATION, TOOL_NAME, \
     REFERENCE_METADATA_ATTR 
from Products.Archetypes.exceptions import ReferenceException

from Acquisition import aq_base, aq_parent, aq_inner
from AccessControl import ClassSecurityInfo
from ExtensionClass import Base
from OFS.SimpleItem import SimpleItem
from OFS.ObjectManager import ObjectManager

from Globals import InitializeClass, DTMLFile
from Products.CMFCore.utils import getToolByName
from Products.CMFCore.utils import UniqueObject
from Products.CMFCore import permissions
from Products.BTreeFolder2.BTreeFolder2 import BTreeFolder2
from Products.PageTemplates.PageTemplateFile import PageTemplateFile
from Products.ZCatalog.ZCatalog import ZCatalog
from Products.ZCatalog.Catalog import Catalog
from Products.ZCatalog.CatalogBrains import AbstractCatalogBrain
from Products import CMFCore
from ZODB.POSException import ConflictError
from zExceptions import NotFound
import zLOG
from AccessControl.Permissions import manage_zcatalog_entries as ManageZCatalogEntries

_www = os.path.join(os.path.dirname(__file__), 'www')
_catalog_dtml = os.path.join(os.path.dirname(CMFCore.__file__), 'dtml')

STRING_TYPES = (StringType, UnicodeType)

from Referenceable import Referenceable
from UIDCatalog import UIDCatalog
from UIDCatalog import UIDCatalogBrains
from UIDCatalog import UIDResolver

class Reference(Referenceable, SimpleItem):
    ## Added base level support for referencing References
    ## They respond to the UUID protocols, but are not
    ## catalog aware. This means that you can't move/rename
    ## reference objects and expect them to work, but you can't
    ## do this anyway. However they should fine the correct
    ## events when they are added/deleted, etc
    implements(INewstyleReference)
    __implements__ = Referenceable.__implements__ + (IReference,)

    security = ClassSecurityInfo()
    portal_type = 'Reference'
    meta_type = 'Reference'

    # XXX FIXME more security

    manage_options = (
        (
        {'label':'View', 'action':'manage_view',
         },
        )+
        SimpleItem.manage_options
        )

    security.declareProtected(permissions.ManagePortal,
                              'manage_view')
    manage_view = PageTemplateFile('view_reference', _www)

    def __init__(self, id, source, target, relationship, **kwargs):
        self.id = id
        setattr(self, UUID_ATTR,  id)

        self.sourceUID = IUID(source)()
        self.targetUID = IUID(target)()
        self.relationship = relationship

        self.__dict__.update(kwargs)
        # Create a list of metadata ids for future reference
        setattr(self, REFERENCE_METADATA_ATTR, kwargs.keys())

    def __repr__(self):
        return "<Reference sid:%s tid:%s rel:%s>" %(self.sourceUID, 
                                                    self.targetUID, 
                                                    self.relationship)

    def UID(self):
        """the uid method for compat"""
        return getattr(aq_base(self), UUID_ATTR)

    ###
    # Catalog support
    def targetId(self):
        meta = IReferenceMetadata(self).getTargetMetadata()
        return meta.get('getId', '')

    def targetTitle(self):
        meta = IReferenceMetadata(self).getTargetMetadata()
        return meta.get('Title', '')
    
    deprecated(targetId, "This method is deprecated, please access "
                                " the target metadata using the "
                                " IReferenceMetadata adapter.")
    deprecated(targetTitle, "This method is deprecated, please access "
                                " the target metadata using the "
                                " IReferenceMetadata adapter.")

    def Type(self):
        return self.__class__.__name__

    ###
    # Policy hooks, subclass away
    def addHook(self, tool, sourceObject=None, targetObject=None):
        #to reject the reference being added raise a ReferenceException
        pass

    def delHook(self, tool, sourceObject=None, targetObject=None):
        #to reject the delete raise a ReferenceException
        pass

    ###
    # OFS Operations Policy Hooks
    # These Hooks are experimental and subject to change
    def beforeTargetDeleteInformSource(self):
        """called before target object is deleted so
        the source can have a say"""
        pass

    def beforeSourceDeleteInformTarget(self):
        """called when the refering source Object is
        about to be deleted"""
        pass

    def manage_afterAdd(self, item, container):
        Referenceable.manage_afterAdd(self, item, container)

        # when copying a full site containe is the container of the plone site
        # and item is the plone site (at least for objects in portal root)
        base = container
        try:
            rc = getToolByName(base, REFERENCE_CATALOG)
        except:
            base = item
            rc = getToolByName(base, REFERENCE_CATALOG)
        url = getRelURL(base, self.getPhysicalPath())
        rc.catalog_object(self, url)


    def manage_beforeDelete(self, item, container):
        Referenceable.manage_beforeDelete(self, item, container)
        rc  = getToolByName(container, REFERENCE_CATALOG)
        url = getRelURL(container, self.getPhysicalPath())
        rc.uncatalog_object(url)


    def _query(self, uid):
        return getUtility(IUIDQuery, context=self).getObject(uid)

    # Use the uid query utility:
    def _getSourceObject(self):
        return self._query(self.sourceUID)

    def _getTargetObject(self):
        return self._query(self.targetUID)
    
    getSourceObject = _getSourceObject 
    getTargetObject = _getTargetObject
    
    deprecated(getSourceObject, "This method is deprecated, please access "
                                " the source object via the attribute"
                                " 'source'.")
    deprecated(getTargetObject, "This method is deprecated, please access "
                                " the target object via the attribute"
                                " 'target'.")

    # Implement the archetypes.reference IReference interface
    source = property(_getSourceObject)
    target = property(_getTargetObject)

InitializeClass(Reference)

REFERENCE_CONTENT_INSTANCE_NAME = 'content'

class ContentReference(ObjectManager, Reference):
    '''Subclass of Reference to support contentish objects inside references '''

    __implements__ = Reference.__implements__ + (IContentReference,)

    def __init__(self, *args, **kw):
        Reference.__init__(self, *args, **kw)

    security = ClassSecurityInfo()
    # XXX FIXME more security

    def addHook(self, *args, **kw):
        # creates the content instance
        if type(self.contentType) in (type(''),type(u'')):
            # type given as string
            tt=getToolByName(self,'portal_types')
            tt.constructContent(self.contentType, self,
                                REFERENCE_CONTENT_INSTANCE_NAME)
        else:
            # type given as class
            setattr(self, REFERENCE_CONTENT_INSTANCE_NAME,
                    self.contentType(REFERENCE_CONTENT_INSTANCE_NAME))
            getattr(self, REFERENCE_CONTENT_INSTANCE_NAME)._md=PersistentMapping()

    def delHook(self, *args, **kw):
        # remove the content instance
        if type(self.contentType) in (type(''),type(u'')):
            # type given as string
            self._delObject(REFERENCE_CONTENT_INSTANCE_NAME)
        else:
            # type given as class
            delattr(self, REFERENCE_CONTENT_INSTANCE_NAME)

    def getContentObject(self):
        return getattr(self.aq_inner.aq_explicit, REFERENCE_CONTENT_INSTANCE_NAME)

    def manage_afterAdd(self, item, container):
        Reference.manage_afterAdd(self, item, container)
        ObjectManager.manage_afterAdd(self, item, container)

    def manage_beforeDelete(self, item, container):
        ObjectManager.manage_beforeDelete(self, item, container)
        Reference.manage_beforeDelete(self, item, container)

InitializeClass(ContentReference)

class ContentReferenceCreator:
    '''Helper class to construct ContentReference instances based
       on a certain content type '''

    security = ClassSecurityInfo()

    def __init__(self,contentType):
        self.contentType=contentType

    def __call__(self,*args,**kw):
        #simulates the constructor call to the reference class in addReference
        res=ContentReference(*args,**kw)
        res.contentType=self.contentType

        return res

InitializeClass(ContentReferenceCreator)

# The brains we want to use

class ReferenceCatalogBrains(UIDCatalogBrains):
    pass


class PluggableCatalog(Catalog):
    # Catalog overrides
    # smarter brains, squirrely traversal

    security = ClassSecurityInfo()
    # XXX FIXME more security

    def useBrains(self, brains):
        """Tricky brains overrides, we need to use our own class here
        with annotation support
        """
        class plugbrains(self.BASE_CLASS, brains):
            pass

        schema = self.schema
        scopy = schema.copy()

        scopy['data_record_id_']=len(schema.keys())
        scopy['data_record_score_']=len(schema.keys())+1
        scopy['data_record_normalized_score_']=len(schema.keys())+2

        plugbrains.__record_schema__ = scopy

        self._v_brains = brains
        self._v_result_class = plugbrains

InitializeClass(PluggableCatalog)

class ReferenceBaseCatalog(PluggableCatalog):
    BASE_CLASS = ReferenceCatalogBrains


class IndexableObjectWrapper(object):
    """Wwrapper for object indexing
    """    
    def __init__(self, obj):
        self._obj = obj
                
    def __getattr__(self, name):
        return getattr(self._obj, name)
        
    def Title(self):
        # TODO: dumb try to make sure UID catalog doesn't fail if Title can't be
        # converted to an ascii string
        # Title is used for sorting only, maybe we could replace it by a better
        # version
        title = self._obj.Title()
        try:
            return str(title)
        except UnicodeDecodeError:
            return self._obj.getId()


class ReferenceCatalog(UniqueObject, UIDResolver, ZCatalog):
    """Reference catalog
    """

    id = REFERENCE_CATALOG
    security = ClassSecurityInfo()
    __implements__ = IReferenceCatalog

    manage_catalogFind = DTMLFile('catalogFind', _catalog_dtml)
    manage_options = ZCatalog.manage_options

    # XXX FIXME more security

    manage_options = ZCatalog.manage_options + \
        ({'label': 'Rebuild catalog',
         'action': 'manage_rebuildCatalog',}, )

    def __init__(self, id, title='', vocab_id=None, container=None):
        """We hook up the brains now"""
        ZCatalog.__init__(self, id, title, vocab_id, container)
        self._catalog = ReferenceBaseCatalog()

    ###
    ## Public API
    def addReference(self, source, target, relationship=None,
                     referenceClass=None, **kwargs):
        source = self._getObject(source)
        target = self._getObject(target)
        ref_source = IReferenceSource(source)
        new_ref = ref_source.addReference(source=source, target=target, 
                                 relationship=(relationship, referenceClass))
        meta_set = IReferenceMetadataSetter(new_ref)
        meta_set.setMetadata(**kwargs)

    deprecated(addReference, "To add references use the addReference()"
                             " method of the IReferenceSource adapter.  "
                             "To set the metadata on the reference, apply the"
                             " IReferenceMetadataSetter adapter to the "
                             " reference object returned by the above method,"
                             " and pass keyword arguments to the setMetadata "
                             "method of that adapter."
                             " This method will be removed in AT 1.6.")

    def deleteReference(self, source, target, relationship=None):
        source = self._getObject(source)
        target = self._getObject(target)
        ref_source = IReferenceSource(source)
        ref_source.deleteReferences(source, target, relationship)

    deprecated(deleteReference, "To delete references use the "
                                "deleteReferences() method of the "
                                "IReferenceSource adapter."
                                " This method will be removed in AT 1.6.")

    def deleteReferences(self, object, relationship=None):
        object = self._getObject(object)
        obj_source = IReferenceSource(object)
        obj_source.deleteReferences()
        ref_query = getUtility(IReferenceQuery, context=self)
        
        # XXX: Why do we delete back references, this is crazy!
        ref_targets = ref_query(target=object, relationship=relationship)
        for ref in ref_targets:
            ref_storage = IReferenceSource(ref.source)
            ref_storage.deleteReferences(ref.source, ref.target,
                                         ref.relationship)

    deprecated(deleteReferences, "To delete references use the "
                                "deleteReferences() method of the "
                                "IReferenceSource adapter.  Additionally, "
                                "If you want to also delete target references"
                                ", as the catalog api did, you'll need to "
                                "query for those with IReferenceQuery and "
                                "delete them similarly."
                                " This method will be removed in AT 1.6.")
     

    def getReferences(self, object, relationship=None, targetObject=None):
        """return a collection of reference objects"""
        object = self._getObject(object)
        ref_query = getUtility(IReferenceQuery, context=self)
        refs = ref_query(source=object, target=targetObject,
                         relationship=relationship)
        return refs

    deprecated(getReferences, "To search for references use the "
                              "IReferenceQuery utility."
                              " This method will be removed in AT 1.6.")
        

    def getBackReferences(self, object, relationship=None, targetObject=None):
        """return a collection of reference objects"""
        object = self._getObject(object)
        targetObject = self._getObject(targetObject)
        ref_query = getUtility(IReferenceQuery, context=self)
        # XXX: This is an incredibly dumb API, targetObject is 
        # passed as source???
        refs = ref_query(source=targetObject, target=object,
                         relationship=relationship)
        return refs

    deprecated(getBackReferences, "To search for references use the "
                                  "IReferenceQuery utility."
                                  " This method will be removed in AT 1.6.")

    def hasRelationshipTo(self, source, target, relationship):
        source = self._getObject(object)
        target = self._getObject(target)
        ref_query = getUtility(IReferenceQuery, context=self) 
        refs = ref_query(source=source, target=target,
                         relationship=relationship)
        return not not refs

    deprecated(hasRelationshipTo, "To search for references use the "
                                  "IReferenceQuery utility."
                                  " This method will be removed in AT 1.6.")

    def getRelationships(self, object):
        """
        Get all relationship types this object has TO other objects
        """
        object = self._getObject(object)
        source = IReferenceSource(object)
        return source.getRelationships()

    deprecated(getRelationships, "To find relationships from a source object,"
                                 " Use the getRelationships() method of the "
                                 "IReferenceSource adapter."
                                 " This method will be removed in AT 1.6.")

    def getBackRelationships(self, object):
        """
        Get all relationship types this object has FROM other objects
        """
        object = self._getObject(object)
        ref_query = getUtility(IReferenceQuery, context=self) 
        refs = ref_query(target=object)
        return [ref.relationship for ref in refs]

    deprecated(getBackRelationships, "To search for references use the "
                                     "IReferenceQuery utility."
                                    " This method will be removed in AT 1.6.")

    def isReferenceable(self, object):
        return (IReferenceable.isImplementedBy(object) or
                shasattr(object, 'isReferenceable'))

    deprecated(getBackRelationships, "The IReferencable API of Archetypes has"
                                     " been replaced by the IReferencable and"
                                     " IReferenceSource interfaces in "
                                     " archetypes.reference"
                                    " This method will be removed in AT 1.6.")

    def _getObject(self, object_or_uid):
        """Returns the actual object.  Accepts either object or uid."""
        if isinstance(object_or_uid, str):
            return getUtility(IUIDQuery, context=self).getObject(object_or_uid)
        else:
            return object_or_uid

    def reference_url(self, object):
        """return a url to an object that will resolve by reference"""
        sID, sobj = self._uidFor(object)
        return "%s/lookupObject?uuid=%s" % (self.absolute_url(), sID)

    def lookupObject(self, uuid, REQUEST=None):
        """Lookup an object by its uuid"""
        obj = self._objectByUUID(uuid)
        if REQUEST:
            return REQUEST.RESPONSE.redirect(obj.absolute_url())
        else:
            return obj

    #####
    ## UID register/unregister
    security.declareProtected(permissions.ModifyPortalContent, 'registerObject')
    def registerObject(self, object):
        self._uidFor(object)

    security.declareProtected(permissions.ModifyPortalContent, 'unregisterObject')
    def unregisterObject(self, object):
        self.deleteReferences(object)
        uc = getToolByName(self,UID_CATALOG)
        uc.uncatalog_object(object._getURL())


    ######
    ## Private/Internal
    def _objectByUUID(self, uuid):
        tool = getToolByName(self, UID_CATALOG)
        brains = tool(UID=uuid)
        for brain in brains:
            obj = brain.getObject()
            if obj is not None:
                return obj
        else:
            return None

    def _queryFor(self, sid=None, tid=None, relationship=None,
                  targetId=None, merge=1):
        """query reference catalog for object matching the info we are
        given, returns brains

        Note: targetId is the actual id of the target object, not its UID
        """

        query = {}
        if sid: query['sourceUID'] = sid
        if tid: query['targetUID'] = tid
        if relationship: query['relationship'] = relationship
        if targetId: query['targetId'] = targetId
        brains = self.searchResults(query, merge=merge)

        return brains


    def _uidFor(self, obj):
        # We should really check for the interface but I have an idea
        # about simple annotated objects I want to play out
        if type(obj) not in STRING_TYPES:
            uobject = aq_base(obj)
            if not self.isReferenceable(uobject):
                raise ReferenceException, "%r not referenceable" % uobject

            # shasattr() doesn't work here
            if not getattr(aq_base(uobject), UUID_ATTR, None):
                uuid = self._getUUIDFor(uobject)
            else:
                uuid = getattr(uobject, UUID_ATTR)
        else:
            uuid = obj
            obj = None
            #and we look up the object
            uid_catalog = getToolByName(self, UID_CATALOG)
            brains = uid_catalog(UID=uuid)
            for brain in brains:
                res = brain.getObject()
                if res is not None:
                    obj = res
        return uuid, obj

    def _getUUIDFor(self, object):
        """generate and attach a new uid to the object returning it"""
        uuid = make_uuid(object.getId())
        setattr(object, UUID_ATTR, uuid)

        return uuid

    def _deleteReference(self, referenceObject):
        try:
            sobj = referenceObject.getSourceObject()
            referenceObject.delHook(self, sobj,
                                    referenceObject.getTargetObject())
        except ReferenceException:
            pass
        else:
            annotation = sobj._getReferenceAnnotations()
            try:
                annotation._delObject(referenceObject.UID())
            except (AttributeError, KeyError):
                pass

    def _resolveBrains(self, brains):
        objects = []
        if brains:
            objects = [b.getObject() for b in brains]
            objects = [b for b in objects if b]
        return objects

    def _makeName(self, *args):
        """get a uuid"""
        name = make_uuid(*args)
        return name

    def __nonzero__(self):
        return 1

    def _catalogReferencesFor(self,obj,path):
        if IReferenceable.isImplementedBy(obj):
            obj._catalogRefs(self)

    def _catalogReferences(self,root=None,**kw):
        ''' catalogs all references, where the optional parameter 'root'
           can be used to specify the tree that has to be searched for references '''

        if not root:
            root=getToolByName(self,'portal_url').getPortalObject()

        path = '/'.join(root.getPhysicalPath())

        results = self.ZopeFindAndApply(root,
                                        search_sub=1,
                                        apply_func=self._catalogReferencesFor,
                                        apply_path=path,**kw)



    def manage_catalogFoundItems(self, REQUEST, RESPONSE, URL2, URL1,
                                 obj_metatypes=None,
                                 obj_ids=None, obj_searchterm=None,
                                 obj_expr=None, obj_mtime=None,
                                 obj_mspec=None, obj_roles=None,
                                 obj_permission=None):

        """ Find object according to search criteria and Catalog them
        """


        elapse = time.time()
        c_elapse = time.clock()

        words = 0
        obj = REQUEST.PARENTS[1]

        self._catalogReferences(obj,obj_metatypes=obj_metatypes,
                                 obj_ids=obj_ids, obj_searchterm=obj_searchterm,
                                 obj_expr=obj_expr, obj_mtime=obj_mtime,
                                 obj_mspec=obj_mspec, obj_roles=obj_roles,
                                 obj_permission=obj_permission)

        elapse = time.time() - elapse
        c_elapse = time.clock() - c_elapse

        RESPONSE.redirect(
            URL1 +
            '/manage_catalogView?manage_tabs_message=' +
            urllib.quote('Catalog Updated\n'
                         'Total time: %s\n'
                         'Total CPU time: %s'
                         % (`elapse`, `c_elapse`))
            )

    security.declareProtected(permissions.ManagePortal, 'manage_rebuildCatalog')
    def manage_rebuildCatalog(self, REQUEST=None, RESPONSE=None):
        """
        """
        elapse = time.time()
        c_elapse = time.clock()

        atool   = getToolByName(self, TOOL_NAME)
        func    = self.catalog_object
        obj     = aq_parent(self)
        path    = '/'.join(obj.getPhysicalPath())
        if not REQUEST:
            REQUEST = self.REQUEST

        # build a list of archetype meta types
        mt = tuple([typ['meta_type'] for typ in atool.listRegisteredTypes()])

        # clear the catalog
        self.manage_catalogClear()

        # find and catalog objects
        self._catalogReferences(obj,
                                obj_metatypes=mt,
                                REQUEST=REQUEST)

        elapse = time.time() - elapse
        c_elapse = time.clock() - c_elapse

        if RESPONSE:
            RESPONSE.redirect(
            REQUEST.URL1 +
            '/manage_catalogView?manage_tabs_message=' +
            urllib.quote('Catalog Rebuilded\n'
                         'Total time: %s\n'
                         'Total CPU time: %s'
                         % (`elapse`, `c_elapse`))
            )

InitializeClass(ReferenceCatalog)


def manage_addReferenceCatalog(self, id, title,
                               vocab_id=None, # Deprecated
                               REQUEST=None):
    """Add a ReferenceCatalog object
    """
    id=str(id)
    title=str(title)
    c=ReferenceCatalog(id, title, vocab_id, self)
    self._setObject(id, c)
    if REQUEST is not None:
        return self.manage_main(self, REQUEST,update_menu=1)

