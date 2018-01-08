from __future__ import unicode_literals

import json

from django import forms
from django.conf import settings
from django.conf.urls import url
from django.contrib import admin, messages
from django.contrib.admin.options import IS_POPUP_VAR
from django.contrib.admin.templatetags.admin_urls import add_preserved_filters
from django.contrib.admin.utils import quote
from django.contrib.admin.views.main import ChangeList
from django.http import (
    Http404,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotAllowed,
    HttpResponseRedirect,
    JsonResponse,
)
from django.template.response import TemplateResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.html import mark_safe
from django.utils.translation import ugettext_lazy as _


class TreeChangeList(ChangeList):

    def url_for_result(self, result):
        pk = getattr(result, self.pk_attname)
        parent = result.get_parent()
        if parent:
            url_name = 'admin:{}_{}_change'.format(
                self.opts.app_label,
                self.opts.model_name
            )
            try:
                return reverse(
                    url_name,
                    kwargs={
                        'node_id': quote(parent.id),
                        'object_id': quote(pk),
                    },
                    current_app=self.model_admin.admin_site.name
                )
            except Exception:
                pass
        return super(TreeChangeList, self).url_for_result(result)


class TreeAdmin(admin.ModelAdmin):

    _node = None

    actions = None
    max_depth = None  # TODO implement max depth
    change_list_template = 'admin/treebeard_admin/tree_list.html'
    change_form_template = 'admin/treebeard_admin/tree_form.html'
    delete_confirmation_template = 'admin/treebeard_admin/tree_delete.html'
    object_history_template = 'admin/treebeard_admin/tree_history.html'

    class Media:
        css = {
            'all': ['admin/treebeard_admin/css/tree.css']
        }
        if 'djangocms_admin_style' in settings.INSTALLED_APPS:
            css['all'].append('admin/treebeard_admin/css/tree.cms.css')
        js = [
            'admin/treebeard_admin/js/changelist.tree.js',
            'admin/treebeard_admin/js/sortable.js',
            'admin/treebeard_admin/js/sortable.tree.js',
        ]

    def get_urls(self):
        info = [
            self.model._meta.app_label,
            self.model._meta.model_name,
        ]
        urls = [

            # Ajax Views
            url(
                r'^update/$',
                self.admin_site.admin_view(self.update_view),
                name='{}_{}_update'.format(*info)
            ),

            # Template Views
            url(
                r'^(?P<node_id>\d+)/list/$',
                self.admin_site.admin_view(self.changelist_view),
                name='{}_{}_changelist'.format(*info)
            ),
            url(
                r'^(?P<node_id>\d+)/add/$',
                self.admin_site.admin_view(self.add_view),
                name='{}_{}_add'.format(*info)
            ),
            url(
                r'^(?P<node_id>\d+)/(?P<object_id>\d+)/change/$',
                self.admin_site.admin_view(self.change_view),
                name='{}_{}_change'.format(*info)
            ),
            url(
                r'^(?P<node_id>\d+)/(?P<object_id>\d+)/delete/$',
                self.admin_site.admin_view(self.delete_view),
                name='{}_{}_delete'.format(*info)
            ),
            url(
                r'^(?P<node_id>\d+)/(?P<object_id>\d+)/history/$',
                self.admin_site.admin_view(self.history_view),
                name='{}_{}_history'.format(*info)
            ),
        ]
        urls += super(TreeAdmin, self).get_urls()
        return urls

    def get_list_display(self, request):
        list_display = ['col_position_node'] + [
            d for d in super(TreeAdmin, self).get_list_display(request)
        ]
        list_display.append('col_node_children_count')
        # TODO implement move ajax
        # list_display.append('col_move_node')
        list_display.append('col_edit_node')
        list_display.append('col_delete_node')
        return list_display

    def get_list_display_links(self, request, list_display):
        return []

    def get_queryset(self, request):
        """
        Only display nodes for the current node or with depth = 1 (root)
        """
        if self._node:
            qs = self._node.get_children()
        else:
            depth = 1
            qs = super(TreeAdmin, self).get_queryset(request)
            qs = qs.filter(depth=depth)
        return qs

    def get_changeform_initial_data(self, request):
        data = super(TreeAdmin, self).get_changeform_initial_data(request)
        if self._node:
            data['tree_parent_id'] = self._node.id
        return data

    def get_node(self, node_id):
        """
        Get the current root node
        """
        if node_id:
            qs = self.model._default_manager.get_queryset()
            try:
                id = int(node_id)
            except ValueError:
                return None
            try:
                return qs.get(pk=id)
            except self.model.DoesNotExist:
                raise Http404(
                    '{} with id "{}" does not exist'.format(
                        self.model._meta.model_name,
                        id
                    )
                )
        return None

    def add_view(self, request, node_id=None, form_url='', extra_context=None):
        self._node = self.get_node(node_id)
        extra_context = extra_context or {}
        extra_context.update({'parent_node': self._node})
        if not form_url and node_id:
            opts = self.model._meta
            form_url = reverse(
                'admin:{}_{}_add'.format(opts.app_label, opts.model_name),
                kwargs={'node_id': node_id},
                current_app=self.admin_site.name
            )
        return super(TreeAdmin, self).add_view(
            request,
            form_url,
            extra_context
        )

    def response_add(self, request, obj, post_url_continue=None):
        if not post_url_continue and self._node:
            opts = self.model._meta
            post_url_continue = reverse(
                'admin:{}_{}_change'.format(opts.app_label, opts.model_name),
                kwargs={'object_id': obj.id, 'node_id': self._node.pk},
                current_app=self.admin_site.name
            )
        return super(TreeAdmin, self).response_add(
            request,
            obj,
            post_url_continue
        )

    def response_post_save_add(self, request, obj):
        """
        Figure out where to redirect after the 'Save' button has been pressed
        when adding a new object.
        """
        print '0huiiiiiiiii'
        opts = self.model._meta
        if self.has_change_permission(request, None):
            post_url = reverse(
                'admin:{}_{}_changelist'.format(
                    opts.app_label,
                    opts.model_name
                ),
                kwargs={'node_id': self._node.pk if self._node.pk else None},
                current_app=self.admin_site.name
            )
            preserved_filters = self.get_preserved_filters(request)
            post_url = add_preserved_filters(
                {'preserved_filters': preserved_filters, 'opts': opts},
                post_url
            )
        else:
            post_url = reverse('admin:index', current_app=self.admin_site.name)
        return HttpResponseRedirect(post_url)

    def change_view(self, request, object_id, node_id=None, form_url='',
                    extra_context=None):
        self._node = self.get_node(node_id)
        extra_context = extra_context or {}
        extra_context.update({'parent_node': self._node})
        if not form_url and self._node:
            opts = self.model._meta
            form_url = reverse(
                'admin:{}_{}_change'.format(opts.app_label, opts.model_name),
                kwargs={'object_id': object_id, 'node_id': self._node.pk},
                current_app=self.admin_site.name
            )
        return super(TreeAdmin, self).change_view(
            request,
            object_id,
            form_url,
            extra_context
        )

    def response_post_save_change(self, request, obj):
        opts = self.model._meta
        if self.has_change_permission(request, None):
            post_url = reverse(
                'admin:{}_{}_changelist'.format(
                    opts.app_label,
                    opts.model_name
                ),
                kwargs={'node_id': self._node.pk if self._node.pk else None},
                current_app=self.admin_site.name
            )
            preserved_filters = self.get_preserved_filters(request)
            post_url = add_preserved_filters(
                {'preserved_filters': preserved_filters, 'opts': opts},
                post_url
            )
        else:
            post_url = reverse('admin:index', current_app=self.admin_site.name)
        return HttpResponseRedirect(post_url)

    def delete_view(self, request, object_id, node_id=None,
                    extra_context=None):
        self._node = self.get_node(node_id)
        extra_context = extra_context or {}
        extra_context.update({'parent_node': self._node})
        return super(TreeAdmin, self).delete_view(
            request,
            object_id,
            extra_context,
        )

    def response_delete(self, request, obj_display, obj_id):
        """
        Determine the HttpResponse for the delete_view stage.
        """
        opts = self.model._meta

        if IS_POPUP_VAR in request.POST:
            popup_response_data = json.dumps({
                'action': 'delete',
                'value': str(obj_id),
            })
            return TemplateResponse(
                request,
                self.popup_response_template or [
                    'admin/{}/{}/popup_response.html'.format(
                        opts.app_label,
                        opts.model_name
                    ),
                    'admin/{}/popup_response.html'.format(
                        opts.app_label
                    ),
                    'admin/popup_response.html',
                ], {
                    'popup_response_data': popup_response_data,
                }
            )

        self.message_user(
            request,
            _('The %(name)s "%(obj)s" was deleted successfully.') % {
                'name': opts.verbose_name,
                'obj': obj_display,
            },
            messages.SUCCESS,
        )

        if self.has_change_permission(request, None):
            url_name = 'admin:{}_{}_changelist'.format(
                opts.app_label,
                opts.model_name
            )
            post_url = reverse(
                url_name,
                kwargs={'node_id': self._node.pk if self._node else None},
                current_app=self.admin_site.name,
            )

            preserved_filters = self.get_preserved_filters(request)
            post_url = add_preserved_filters(
                {'preserved_filters': preserved_filters, 'opts': opts},
                post_url
            )
        else:
            post_url = reverse('admin:index', current_app=self.admin_site.name)
        return HttpResponseRedirect(post_url)

    def history_view(self, request, object_id, node_id=None,
                     extra_context=None):
        self._node = self.get_node(node_id)
        extra_context = extra_context or {}
        extra_context.update({'parent_node': self._node})
        return super(TreeAdmin, self).history_view(
            request,
            object_id,
            extra_context
        )

    def changelist_view(self, request, node_id=None, extra_context=None):
        self._node = self.get_node(node_id)
        extra_context = extra_context or {}
        extra_context.update({
            'parent_node': self._node,
            'add_url': self.get_add_url(),
            'update_url': self.get_update_url(),
        })
        return super(TreeAdmin, self).changelist_view(
            request,
            extra_context,
        )

    def get_changelist(self, request, **kwargs):
        return TreeChangeList

    def get_add_url(self):
        if self._node:
            url_name = 'admin:{}_{}_add'.format(
                self.model._meta.app_label,
                self.model._meta.model_name
            )
            return reverse(url_name, kwargs={'node_id': self._node.id})
        url_name = 'admin:{}_{}_add'.format(
            self.model._meta.app_label,
            self.model._meta.model_name
        )
        return reverse(url_name)

    def get_update_url(self):
        url_name = 'admin:{}_{}_update'.format(
            self.model._meta.app_label,
            self.model._meta.model_name
        )
        return reverse(url_name)

    def update_view(self, request):
        if not request.is_ajax() or request.method != 'POST':
            return HttpResponseBadRequest('Not an XMLHttpRequest')
        if request.method != 'POST':
            return HttpResponseNotAllowed('Must be a POST request')
        if not self.has_change_permission(request):
            return HttpResponseForbidden(
                'Missing permissions to perform this request'
            )
        Form = self.get_update_form_class()
        form = Form(request.POST)
        if form.is_valid():
            data = {'message': 'ok'}
            pos = form.cleaned_data.get('pos')
            parent = form.cleaned_data.get('parent')
            node = form.cleaned_data.get('node')
            target = form.cleaned_data.get('target')
            if pos == 'first':
                if parent:
                    node.move(parent, pos='first-child')
                else:
                    target = node.get_first_root_node()
                    node.move(target, pos='left')
            elif pos == 'last':
                if parent:
                    node.move(parent, pos='last-child')
                else:
                    target = node.get_last_root_node()
                    node.move(target, pos='right')
            else:
                node.move(target, pos=pos)
            node = self.model.objects.get(pk=node.pk)
            node.save()
        else:
            data = {
                'message': 'error',
                'error': _('There seams to be a problem with your list')
            }
        return JsonResponse(data)

    def get_update_form_class(self):
        class UpdateForm(forms.Form):
            depth = forms.IntegerField()
            pos = forms.ChoiceField(
                choices=[
                    ('left', 'left'),
                    ('right', 'right'),
                    ('last', 'last'),
                    ('first', 'first'),
                ]
            )
            node = forms.ModelChoiceField(
                queryset=self.model._default_manager.get_queryset()
            )
            target = forms.ModelChoiceField(
                queryset=self.model._default_manager.get_queryset()
            )
            parent = forms.ModelChoiceField(
                required=False,
                queryset=self.model._default_manager.get_queryset()
            )
        return UpdateForm

    def col_position_node(self, obj):
        data_attrs = [
            'data-pk="{}"'.format(obj.pk),
            'data-depth="{}"'.format(obj.depth),
            'data-name="{}"'.format(obj),
        ]
        if self._node:
            data_attrs.append('data-parent="{}"'.format(self._node.pk))
        html = '<span class="treebeard-admin-drag" {}></span>'.format(
            ' '.join(data_attrs)
        )
        return mark_safe(html)
    col_position_node.short_description = ''

    def col_move_node(self, obj):
        css_classes = 'icon-button treebeard-admin-icon-button place'
        data_attrs = [
            'data-pk="{}"'.format(obj.pk),
            'data-depth="{}"'.format(obj.depth),
            'data-name="{}"'.format(obj),
        ]
        html = '<span class="{}" {}>{}</span>'.format(
            css_classes,
            ' '.join(data_attrs),
            render_to_string('admin/svg/icon-move.svg')
        )
        return mark_safe(html)
    col_move_node.short_description = _('Move')

    def col_delete_node(self, obj):
        info = [self.model._meta.app_label, self.model._meta.model_name]
        css_classes = 'icon-button treebeard-admin-icon-button delete'
        if self._node:
            delete_url = reverse(
                'admin:{}_{}_delete'.format(*info),
                kwargs={'object_id': obj.pk, 'node_id': self._node.pk},
                current_app=self.admin_site.name
            )
        else:
            delete_url = reverse(
                'admin:{}_{}_delete'.format(*info),
                args=[obj.pk],
                current_app=self.admin_site.name
            )
        html_data_attrs = 'data-id="{}" data-delete-url="{}"'.format(
            obj.id,
            delete_url
        )
        html = '<a class="{}" href="{}" {}>{}</a>'.format(
            css_classes,
            delete_url,
            html_data_attrs,
            render_to_string('admin/svg/icon-delete.svg')
        )
        return mark_safe(html)
    col_delete_node.short_description = _('Delete')

    def col_edit_node(self, obj):
        info = [self.model._meta.app_label, self.model._meta.model_name]
        css_classes = 'icon-button treebeard-admin-icon-button edit'
        if self._node:
            url_edit = reverse(
                'admin:{}_{}_change'.format(*info),
                kwargs={'object_id': obj.pk, 'node_id': self._node.pk},
                current_app=self.admin_site.name
            )
        else:
            url_edit = reverse(
                'admin:{}_{}_change'.format(*info),
                args=[obj.pk],
                current_app=self.admin_site.name
            )
        url_list = reverse(
            'admin:{}_{}_changelist'.format(*info),
            kwargs={'node_id': obj.pk},
            current_app=self.admin_site.name
        )

        data_attrs = [
            'data-id="{}"'.format(obj.id),
            'data-edit-url="{}"'.format(url_edit),
            'data-list-url="{}"'.format(url_list),
        ]
        html = '<a class="{}" href="{}" {}>{}</a>'.format(
            css_classes,
            url_edit,
            ' '.join(data_attrs),
            render_to_string('admin/svg/icon-edit.svg')
        )
        return mark_safe(html)
    col_edit_node.short_description = _('Edit')

    def col_node_children_count(self, obj):
        html = '{}'.format(obj.get_children_count())
        return mark_safe(html)
    col_node_children_count.short_description = _('Children')


class TreeAdminWithSideTree(TreeAdmin):
    pass