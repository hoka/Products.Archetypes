from Products.Archetypes.Schema import Schema
from Products.Archetypes.Field import StringField
from Products.Archetypes.Widget import SelectionWidget
from Products.Archetypes.config import TOOL_NAME
from Products.Archetypes.interfaces.ITemplateMixin import ITemplateMixin

try:
    from Products.CMFCore import permissions as CMFCorePermissions
except ImportError:
    from Products.CMFCore import CMFCorePermissions
from Products.CMFCore.utils import getToolByName
from AccessControl import ClassSecurityInfo
from Globals import InitializeClass
from Acquisition import aq_base
from Acquisition import aq_inner
from Acquisition import aq_parent
from ExtensionClass import Base

TemplateMixinSchema = Schema((
    # TemplateMixin
    StringField('layout',
                write_permission=CMFCorePermissions.ModifyPortalContent,
                default_method="getDefaultLayout",
                vocabulary="_voc_templates",
                # we can't use enforce because we may use the view name from the
                # type information
                #enforceVocabulary=1,
                widget=SelectionWidget(description="Choose a template that will be used for viewing this item.",
                                       description_msgid = "help_template_mixin",
                                       label = "View template",
                                       label_msgid = "label_template_mixin",
                                       i18n_domain = "plone",
                                       visible={'view' : 'hidden',
                                                'edit' : 'visible'
                                               },
                                       )),
    ))


class TemplateMixin(Base):
    __implements__ = ITemplateMixin

    schema = TemplateMixinSchema

    actions = (
        { 'id': 'view',
          'name': 'View',
          'action': 'string:${object_url}/',
          'permissions': (CMFCorePermissions.View,),
        },
        )

    aliases = {
        '(Default)': '',
        'index_html': '',
        'view': '',
        'gethtml': 'source_html',
        }

    # if default_view is None TemplateMixin is using the immediate_view from
    # the type information
    default_view = None
    suppl_views = ()

    security = ClassSecurityInfo()

    index_html = None # setting index_html to None forces the usage of __call__

    def __call__(self):
        """return a view based on layout"""
        v = self.getTemplateFor(self.getLayout())
        # rewrap the template in the right context
        context = aq_inner(self)
        v = v.__of__(context)
        return v(context, context.REQUEST)

    def _voc_templates(self):
        at = getToolByName(self, TOOL_NAME)
        return at.lookupTemplates(self)

    # XXX backward compatibility
    templates = _voc_templates

    security.declareProtected(CMFCorePermissions.View, 'getLayout')
    def getLayout(self, **kw):
        """Get the current layout or the default layout if the current one is None
        """
        if kw.has_key('schema'):
            schema = kw['schema']
        else:
            schema = self.Schema()
            kw['schema'] = schema
        value = schema['layout'].get(self, **kw)
        if value:
            return value
        else:
            return self.getDefaultLayout()

    security.declareProtected(CMFCorePermissions.View, 'getDefaultLayout')
    def getDefaultLayout(self):
        """Get the default layout used for TemplateMixin.

        Check the class definition for a attribute called 'default_view' then
        check the Factory Type Information (portal_types) for an attribute
        immediate_view else finally return the 'base_view' string which is a
        autogenerated form from Archetypes.
        """
        default_view = getattr(aq_base(self), 'default_view', None)
        if default_view:
            return default_view
        immediate_view = getattr(self.getTypeInfo(), 'immediate_view', None)
        if immediate_view:
            return immediate_view
        return 'base_view'

    def getTemplateFor(self, pt, default='base_view'):
        """Let the SkinManager handle this.

        But always try to show something.
        """
        pt = getattr(self, pt, None)
        if not pt:
            # default is the value of obj.default_view or base_view
            default_pt = getattr(self, 'default_view', None)
            if not default_pt:
                default_pt = default
            return getattr(self, default_pt)
        else:
            return pt


InitializeClass(TemplateMixin)

# XXX backward compatibility
schema = TemplateMixinSchema
getTemplateFor = TemplateMixin.getTemplateFor

__all__ = ('TemplateMixinSchema', 'TemplateMixin', )
