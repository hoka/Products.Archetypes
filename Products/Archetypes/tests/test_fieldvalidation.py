# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2002-2005, Benjamin Saller <bcsaller@ideasuite.com>, and 
#	                       the respective authors. All rights reserved.
# For a list of Archetypes contributors see docs/CREDITS.txt.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
# * Neither the name of the author nor the names of its contributors may be used
#   to endorse or promote products derived from this software without specific
#   prior written permission.
#
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE.
#
################################################################################

import os, sys
if __name__ == '__main__':
    execfile(os.path.join(sys.path[0], 'framework.py'))

from common import *
from utils import *

from Products.Archetypes.atapi import *
from Products.Archetypes.config import *
from Products.Archetypes.bases.baseobject import BaseObject

from Products.Archetypes.validation import validationService
from Products.Archetypes.interfaces.IValidator import IValidator

class MyValidator:
    __implements__ = (IValidator,)

    def __init__(self, name, fun):
        self.name = name
        self.fun = fun

    def __call__(self, value, instance, field, *args, **kwargs):
        return self.fun(value)

# never validates
validationService.register(MyValidator('v1', lambda val:val))
# always validates
validationService.register(MyValidator('v2', lambda val:1))
# never validates
validationService.register(MyValidator('v3', lambda val:[]))

settings = [
    {'field': {}, # this is the dict of field properties
     'value': None,
     'assertion': lambda result:result is None, # result of field.validate()
     },

    {'field': {'required': 1}, # required
     'value': None,            # ... but no value given
     'assertion': lambda result:result is not None},

    ]

for req in 0,1: # 0 == not required, 1 == required

    for validator in (('v2', 'v1'), ('v1',)):
        # Make sure that for both sets of validators, v1 returns an error.
        settings.append(
            {'field': {'required': req, 'validators': validator},
             'value': 'bass',
             'assertion': lambda result:result.find('bass') > -1}
            )

    # the trombone is in the vocabulary
    settings.append(
        {'field': {'required': req, 'enforceVocabulary': 1,
                   'vocabulary': ('frenchhorn', 'trombone', 'trumpet')},
         'value': 'trombone',
         'assertion': lambda result:result is None}
        )

    # tuba is not in vocabulary, so this must fail
    settings.append(
        {'field': {'required': req, 'enforceVocabulary': 1,
                   'vocabulary': ('frenchhorn', 'trombone', 'trumpet')},
         'value': 'tuba',
         'assertion': lambda result:result is not None}
        )

    # enforceVocabulary, but no vocabulary given
    settings.append(
        {'field': {'required': req, 'enforceVocabulary': 1},
         'value': 'cello',
         'assertion': lambda result:result is not None}
        )


class FakeType(BaseObject):
    def unicodeEncode(self, v): return v # don't


class TestSettings(ArchetypesTestCase):

    def afterSetUp(self):
        self.instance = FakeType('fake')

    def testSettings(self):
        # tests every setting in global "settings"
        for setting in settings:
            field = Field('orchestra', **setting['field'])
            result = field.validate(setting['value'], self.instance, errors={})
            msg = 'Assertion failed for setting:\n%s.\nResult was "%s".' % \
                  (setting, result)

            self.assert_(setting['assertion'](result),
                         setting.get('failmsg', msg))


class TestValidation(ArchetypesTestCase):

    def afterSetUp(self):
        self.instance = FakeType('fake')

    def testIntegerZeroInvalid(self):
        # attach a validator that never validates, so any value must fail
        field = IntegerField('integer', validators=('v3',))

        self.assert_(field.validate(1, self.instance, errors={}) is not None)
        self.assert_(field.validate(0, self.instance, errors={}) is not None)


def test_suite():
    from unittest import TestSuite, makeSuite
    suite = TestSuite()
    suite.addTest(makeSuite(TestSettings))
    suite.addTest(makeSuite(TestValidation))
    return suite

if __name__ == '__main__':
    framework()

