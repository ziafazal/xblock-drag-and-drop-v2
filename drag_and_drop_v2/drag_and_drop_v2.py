# -*- coding: utf-8 -*-
#

# Imports ###########################################################

import json
import webob
import copy
import urllib

from xblock.core import XBlock
from xblock.exceptions import JsonHandlerError
from xblock.fields import Scope, String, Dict, Float, Boolean, Integer
from xblock.fragment import Fragment
from xblockutils.resources import ResourceLoader
from xblockutils.settings import XBlockWithSettingsMixin, ThemableXBlockMixin

from .utils import _, ngettext as ngettext_fallback
from .default_data import DEFAULT_DATA


# Globals ###########################################################

loader = ResourceLoader(__name__)


# Classes ###########################################################

@XBlock.wants('settings')
@XBlock.needs('i18n')
class DragAndDropBlock(XBlock, XBlockWithSettingsMixin, ThemableXBlockMixin):
    """
    XBlock that implements a friendly Drag-and-Drop problem
    """
    STANDARD_MODE = "standard"
    ASSESSMENT_MODE = "assessment"

    display_name = String(
        display_name=_("Title"),
        help=_("The title of the drag and drop problem. The title is displayed to learners."),
        scope=Scope.settings,
        default=_("Drag and Drop"),
    )

    mode = String(
        display_name=_("Mode"),
        help=_(
            "Standard mode: the problem provides immediate feedback each time "
            "a learner drops an item on a target zone. "
            "Assessment mode: the problem provides feedback only after "
            "a learner drops all available items on target zones."
        ),
        scope=Scope.settings,
        values=[
            {"display_name": _("Standard"), "value": STANDARD_MODE},
            {"display_name": _("Assessment"), "value": ASSESSMENT_MODE},
        ],
        default=STANDARD_MODE
    )

    max_attempts = Integer(
        display_name=_("Maximum attempts"),
        help=_(
            "Defines the number of times a student can try to answer this problem. "
            "If the value is not set, infinite attempts are allowed."
        ),
        scope=Scope.settings,
        default=None,
    )

    show_title = Boolean(
        display_name=_("Show title"),
        help=_("Display the title to the learner?"),
        scope=Scope.settings,
        default=True,
    )

    question_text = String(
        display_name=_("Problem text"),
        help=_("The description of the problem or instructions shown to the learner"),
        scope=Scope.settings,
        default="",
    )

    show_question_header = Boolean(
        display_name=_('Show "Problem" heading'),
        help=_('Display the heading "Problem" above the problem text?'),
        scope=Scope.settings,
        default=True,
    )

    weight = Float(
        display_name=_("Weight"),
        help=_("The maximum score the learner can receive for the problem"),
        scope=Scope.settings,
        default=1,
    )

    item_background_color = String(
        display_name=_("Item background color"),
        help=_("The background color of draggable items in the problem."),
        scope=Scope.settings,
        default="",
    )

    item_text_color = String(
        display_name=_("Item text color"),
        help=_("Text color to use for draggable items."),
        scope=Scope.settings,
        default="",
    )

    data = Dict(
        display_name=_("Problem data"),
        help=_(
            "Information about zones, items, feedback, and background image for this problem. "
            "This information is derived from the input that a course author provides via the interactive editor "
            "when configuring the problem."
        ),
        scope=Scope.content,
        default=DEFAULT_DATA,
    )

    item_state = Dict(
        help=_("Information about current positions of items that a learner has dropped on the target image."),
        scope=Scope.user_state,
        default={},
    )

    num_attempts = Integer(
        help=_("Number of attempts learner used"),
        scope=Scope.user_state,
        default=0
    )

    completed = Boolean(
        help=_("Indicates whether a learner has completed the problem at least once"),
        scope=Scope.user_state,
        default=False,
    )

    block_settings_key = 'drag-and-drop-v2'
    has_score = True

    @XBlock.supports("multi_device")  # Enable this block for use in the mobile app via webview
    def student_view(self, context):
        """
        Player view, displayed to the student
        """

        fragment = Fragment()
        fragment.add_content(loader.render_template('/templates/html/drag_and_drop.html'))
        css_urls = (
            'public/css/vendor/jquery-ui-1.10.4.custom.min.css',
            'public/css/drag_and_drop.css'
        )
        js_urls = (
            'public/js/vendor/jquery-ui-1.10.4.custom.min.js',
            'public/js/vendor/jquery-ui-touch-punch-0.2.3.min.js',  # Makes it work on touch devices
            'public/js/vendor/virtual-dom-1.3.0.min.js',
            'public/js/drag_and_drop.js',
        )
        for css_url in css_urls:
            fragment.add_css_url(self.runtime.local_resource_url(self, css_url))
        for js_url in js_urls:
            fragment.add_javascript_url(self.runtime.local_resource_url(self, js_url))

        self.include_theme_files(fragment)

        fragment.initialize_js('DragAndDropBlock', self.get_configuration())

        return fragment

    def get_configuration(self):
        """
        Get the configuration data for the student_view.
        The configuration is all the settings defined by the author, except for correct answers
        and feedback.
        """

        def items_without_answers():
            items = copy.deepcopy(self.data.get('items', ''))
            for item in items:
                del item['feedback']
                # Use item.pop to remove both `item['zone']` and `item['zones']`; we don't have
                # a guarantee that either will be present, so we can't use `del`. Legacy instances
                # will have `item['zone']`, while current versions will have `item['zones']`.
                item.pop('zone', None)
                item.pop('zones', None)
                # Fall back on "backgroundImage" to be backward-compatible.
                image_url = item.get('imageURL') or item.get('backgroundImage')
                if image_url:
                    item['expandedImageURL'] = self._expand_static_url(image_url)
                else:
                    item['expandedImageURL'] = ''
            return items

        return {
            "mode": self.mode,
            "max_attempts": self.max_attempts,
            "zones": self._get_zones(),
            # SDK doesn't supply url_name.
            "url_name": getattr(self, 'url_name', ''),
            "display_zone_labels": self.data.get('displayLabels', False),
            "display_zone_borders": self.data.get('displayBorders', False),
            "items": items_without_answers(),
            "title": self.display_name,
            "show_title": self.show_title,
            "problem_text": self.question_text,
            "show_problem_header": self.show_question_header,
            "target_img_expanded_url": self.target_img_expanded_url,
            "target_img_description": self.target_img_description,
            "item_background_color": self.item_background_color or None,
            "item_text_color": self.item_text_color or None,
            "initial_feedback": self.data['feedback']['start'],
            # final feedback (data.feedback.finish) is not included - it may give away answers.
        }

    def studio_view(self, context):
        """
        Editing view in Studio
        """

        js_templates = loader.load_unicode('/templates/html/js_templates.html')
        help_texts = {
            field_name: self.ugettext(field.help)
            for field_name, field in self.fields.viewitems() if hasattr(field, "help")
        }
        field_values = {
            field_name: field.values
            for field_name, field in self.fields.viewitems() if hasattr(field, "values")
        }
        context = {
            'js_templates': js_templates,
            'help_texts': help_texts,
            'field_values': field_values,
            'self': self,
            'data': urllib.quote(json.dumps(self.data)),
        }

        fragment = Fragment()
        fragment.add_content(loader.render_template('/templates/html/drag_and_drop_edit.html', context))

        css_urls = (
            'public/css/vendor/jquery-ui-1.10.4.custom.min.css',
            'public/css/drag_and_drop_edit.css'
        )
        js_urls = (
            'public/js/vendor/jquery-ui-1.10.4.custom.min.js',
            'public/js/vendor/handlebars-v1.1.2.js',
            'public/js/drag_and_drop_edit.js',
        )
        for css_url in css_urls:
            fragment.add_css_url(self.runtime.local_resource_url(self, css_url))
        for js_url in js_urls:
            fragment.add_javascript_url(self.runtime.local_resource_url(self, js_url))

        # Do a bit of manipulation so we get the appearance of a list of zone options on
        # items that still have just a single zone stored

        items = self.data.get('items', [])

        for item in items:
            zones = self._get_item_zones(item['id'])
            # Note that we appear to be mutating the state of the XBlock here, but because
            # the change won't be committed, we're actually just affecting the data that
            # we're going to send to the client, not what's saved in the backing store.
            item['zones'] = zones
            item.pop('zone', None)

        fragment.initialize_js('DragAndDropEditBlock', {
            'data': self.data,
            'target_img_expanded_url': self.target_img_expanded_url,
            'default_background_image_url': self.default_background_image_url,
        })

        return fragment

    @XBlock.json_handler
    def studio_submit(self, submissions, suffix=''):
        self.display_name = submissions['display_name']
        self.mode = submissions['mode']
        self.max_attempts = submissions['max_attempts']
        self.show_title = submissions['show_title']
        self.question_text = submissions['problem_text']
        self.show_question_header = submissions['show_problem_header']
        self.weight = float(submissions['weight'])
        self.item_background_color = submissions['item_background_color']
        self.item_text_color = submissions['item_text_color']
        self.data = submissions['data']

        return {
            'result': 'success',
        }

    @XBlock.json_handler
    def drop_item(self, item_attempt, suffix=''):
        self._validate_drop_item(item_attempt)

        if self.mode == self.ASSESSMENT_MODE:
            return self._drop_item_assessment(item_attempt)
        elif self.mode == self.STANDARD_MODE:
            return self._drop_item_standard(item_attempt)
        else:
            raise JsonHandlerError(500, _("Unknown DnDv2 mode {mode} - course is misconfigured").format(self.mode))

    @XBlock.json_handler
    def do_attempt(self, data, suffix=''):
        ngettext = self._get_ngettext()
        self._validate_attempt()

        self.num_attempts += 1
        self._mark_complete_and_publish_grade()

        required, placed, correct = self._get_item_raw_stats()
        placed_ids, correct_ids = set(placed), set(correct)
        missing_ids = set(required) - set(placed)
        misplaced_ids = placed_ids - correct_ids

        correct_count, misplaced_count, missing_count = len(correct_ids), len(misplaced_ids), len(missing_ids)

        feedback_msgs = [
            ngettext(
                'Correctly placed {correct_count} item.',
                'Correctly placed {correct_count} items.',
                correct_count
            ).format(correct_count=correct_count),
            ngettext(
                'Misplaced {misplaced_count} item.',
                'Misplaced {misplaced_count} items.',
                misplaced_count
            ).format(misplaced_count=misplaced_count),
            ngettext(
                'Not placed {missing_count} required item.',
                'Not placed {missing_count} required items.',
                missing_count
            ).format(missing_count=missing_count)
        ]

        if misplaced_ids and self.attemps_remain:
            feedback_msgs.append(_('Misplaced items were returned to item bank.'))

        if not misplaced_ids and not missing_ids:
            feedback_msgs.append(self.data['feedback']['finish'])

        for item_id in misplaced_ids:
            del self.item_state[item_id]

        if not self.attemps_remain:
            feedback_msgs.append(_('Final attempt was used, final score is {score}').format(score=self._get_grade()))

        return {
            'num_attempts': self.num_attempts,
            'misplaced_items': list(misplaced_ids),
            'feedback': ''.join(["<p>{}</p>".format(msg) for msg in feedback_msgs])
        }

    def _validate_attempt(self):
        if self.mode != self.ASSESSMENT_MODE:
            raise JsonHandlerError(400, _("do_attempt handler should only be called for assessment mode"))
        if not self.attemps_remain:
            raise JsonHandlerError(409, _("Max number of attempts reached"))

    @XBlock.json_handler
    def publish_event(self, data, suffix=''):
        try:
            event_type = data.pop('event_type')
        except KeyError:
            return {'result': 'error', 'message': 'Missing event_type in JSON data'}

        self.runtime.publish(self, event_type, data)
        return {'result': 'success'}

    @XBlock.json_handler
    def reset(self, data, suffix=''):
        self.item_state = {}
        return self._get_user_state()

    @XBlock.json_handler
    def expand_static_url(self, url, suffix=''):
        """ AJAX-accessible handler for expanding URLs to static [image] files """
        return {'url': self._expand_static_url(url)}

    @property
    def target_img_expanded_url(self):
        """ Get the expanded URL to the target image (the image items are dragged onto). """
        if self.data.get("targetImg"):
            return self._expand_static_url(self.data["targetImg"])
        else:
            return self.default_background_image_url

    @property
    def target_img_description(self):
        """ Get the description for the target image (the image items are dragged onto). """
        return self.data.get("targetImgDescription", "")

    @property
    def default_background_image_url(self):
        """ The URL to the default background image, shown when no custom background is used """
        return self.runtime.local_resource_url(self, "public/img/triangle.png")

    @property
    def attemps_remain(self):
        return self.max_attempts is None or self.max_attempts == 0 or self.num_attempts < self.max_attempts

    @XBlock.handler
    def get_user_state(self, request, suffix=''):
        """ GET all user-specific data, and any applicable feedback """
        data = self._get_user_state()
        return webob.Response(body=json.dumps(data), content_type='application/json')

    def _get_ngettext(self):
        i18n_service = self.runtime.service(self, "i18n")
        if i18n_service:
            return i18n_service.ngettext
        else:
            return ngettext_fallback

    def _drop_item_standard(self, item_attempt):
        item = self._get_item_definition(item_attempt['val'])

        is_correct = self._is_attempt_correct(item_attempt)  # Student placed item in a correct zone
        if is_correct:  # In standard mode state is only updated when attempt is correct
            self.item_state[str(item['id'])] = self._make_state_from_attempt(item_attempt, is_correct)

        self._mark_complete_and_publish_grade()
        self._publish_item_dropped_event(item_attempt, is_correct)

        item_feedback_key = 'correct' if is_correct else 'incorrect'
        item_feedback = item['feedback'][item_feedback_key]
        overall_feedback = self.data['feedback']['finish'] if self._is_finished() else None

        return {
            'correct': is_correct,
            'finished': self._is_finished(),
            'overall_feedback': overall_feedback,
            'feedback': item_feedback
        }

    def _drop_item_assessment(self, item_attempt):
        if not self.attemps_remain:
            raise JsonHandlerError(409, _("Max number of attempts reached"))

        item = self._get_item_definition(item_attempt['val'])

        is_correct = self._is_attempt_correct(item_attempt)
        # State is always updated in assessment mode to store intermediate item positions
        self.item_state[str(item['id'])] = self._make_state_from_attempt(item_attempt, is_correct)

        self._publish_item_dropped_event(item_attempt, is_correct)

        return {}

    def _validate_drop_item(self, item):
        zone = self._get_zone_by_uid(item['zone'])
        if not zone:
            raise JsonHandlerError(400, "Item zone data invalid.")

    @staticmethod
    def _make_state_from_attempt(attempt, correct):
        return {
            'zone': attempt['zone'],
            'correct': correct,
            'x_percent': attempt['x_percent'],
            'y_percent': attempt['y_percent'],
        }

    def _mark_complete_and_publish_grade(self):
        # don't publish the grade if the student has already completed the problem
        if not self.completed:
            self.completed = self._is_finished() or not self.attemps_remain
            self._publish_grade()

    def _publish_grade(self):
        try:
            self.runtime.publish(self, 'grade', {
                'value': self._get_grade(),
                'max_value': self.weight,
            })
        except NotImplementedError:
            # Note, this publish method is unimplemented in Studio runtimes,
            # so we have to figure that we're running in Studio for now
            pass

    def _publish_item_dropped_event(self, attempt, is_correct):
        item = self._get_item_definition(attempt['val'])
        # attempt should already be validated here - not doing the check for existing zone again
        zone = self._get_zone_by_uid(attempt['zone'])

        self.runtime.publish(self, 'edx.drag_and_drop_v2.item.dropped', {
            'item_id': item['id'],
            'location': zone.get("title"),
            'location_id': zone.get("uid"),
            'is_correct': is_correct,
        })

    def _is_attempt_correct(self, attempt):
        """
        Check if the item was placed correctly.
        """
        correct_zones = self._get_item_zones(attempt['val'])
        return attempt['zone'] in correct_zones

    def _expand_static_url(self, url):
        """
        This is required to make URLs like '/static/dnd-test-image.png' work (note: that is the
        only portable URL format for static files that works across export/import and reruns).
        This method is unfortunately a bit hackish since XBlock does not provide a low-level API
        for this.
        """
        if hasattr(self.runtime, 'replace_urls'):
            url = self.runtime.replace_urls('"{}"'.format(url))[1:-1]
        elif hasattr(self.runtime, 'course_id'):
            # edX Studio uses a different runtime for 'studio_view' than 'student_view',
            # and the 'studio_view' runtime doesn't provide the replace_urls API.
            try:
                from static_replace import replace_static_urls  # pylint: disable=import-error
                url = replace_static_urls('"{}"'.format(url), None, course_id=self.runtime.course_id)[1:-1]
            except ImportError:
                pass
        return url

    def _get_user_state(self):
        """ Get all user-specific data, and any applicable feedback """
        item_state = self._get_item_state()
        for item_id, item in item_state.iteritems():
            # If information about zone is missing
            # (because problem was completed before a11y enhancements were implemented),
            # deduce zone in which item is placed from definition:
            if item.get('zone') is None:
                valid_zones = self._get_item_zones(int(item_id))
                if valid_zones:
                    # If we get to this point, then the item was placed prior to support for
                    # multiple correct zones being added. As a result, it can only be correct
                    # on a single zone, and so we can trust that the item was placed on the
                    # zone with index 0.
                    item['zone'] = valid_zones[0]
                else:
                    item['zone'] = 'unknown'

        is_finished = self._is_finished()
        return {
            'items': item_state,
            'finished': is_finished,
            'num_attempts': self.num_attempts,
            'overall_feedback': self.data['feedback']['finish' if is_finished else 'start'],
        }

    def _get_item_state(self):
        """
        Returns the user item state.
        Converts to a dict if data is stored in legacy tuple form.
        """
        state = {}

        for item_id, item in self.item_state.iteritems():
            if isinstance(item, dict):
                state[item_id] = item
            else:
                state[item_id] = {'top': item[0], 'left': item[1]}

        return state

    def _get_item_definition(self, item_id):
        """
        Returns definition (settings) for item identified by `item_id`.
        """
        return next(i for i in self.data['items'] if i['id'] == item_id)

    def _get_item_zones(self, item_id):
        """
        Returns a list of the zones that are valid options for the item.

        If the item is configured with a list of zones, return that list. If
        the item is configured with a single zone, encapsulate that zone's
        ID in a list and return the list. If the item is not configured with
        any zones, or if it's configured explicitly with no zones, return an
        empty list.
        """
        item = self._get_item_definition(item_id)
        if item.get('zones') is not None:
            return item.get('zones')
        elif item.get('zone') is not None and item.get('zone') != 'none':
            return [item.get('zone')]
        else:
            return []

    def _get_zones(self):
        """
        Get drop zone data, defined by the author.
        """
        # Convert zone data from old to new format if necessary
        zones = []
        for zone in self.data.get('zones', []):
            zone = zone.copy()
            if "uid" not in zone:
                zone["uid"] = zone.get("title")  # Older versions used title as the zone UID
            # Remove old, now-unused zone attributes, if present:
            zone.pop("id", None)
            zone.pop("index", None)
            zones.append(zone)
        return zones

    def _get_zone_by_uid(self, uid):
        """
        Given a zone UID, return that zone, or None.
        """
        for zone in self._get_zones():
            if zone["uid"] == uid:
                return zone

    def _get_item_stats(self):
        """
        Returns a tuple representing the number of correctly-placed items,
        and the total number of items that must be placed on the board (non-decoy items).
        """
        required_items, _, correct_items = self._get_item_raw_stats()

        return len(correct_items), len(required_items)

    def _get_item_raw_stats(self):
        """
        Returns a 3-tuple containing required, placed and correct items.
        """
        all_items = [str(item['id']) for item in self.data['items']]
        item_state = self._get_item_state()

        required_items = [item_id for item_id in all_items if self._get_item_zones(int(item_id)) != []]
        placed_items = [item_id for item_id in all_items if item_id in item_state]
        correct_items = [item_id for item_id in placed_items if item_state[item_id]['correct']]

        return required_items, placed_items, correct_items

    def _get_grade(self):
        """
        Returns the student's grade for this block.
        """
        correct_count, required_count = self._get_item_stats()
        return correct_count / float(required_count) * self.weight

    def _is_finished(self):
        """
        All items are at their correct place and a value has been
        submitted for each item that expects a value.
        """
        correct_count, required_count = self._get_item_stats()
        return correct_count == required_count

    def _get_unique_id(self):
        usage_id = self.scope_ids.usage_id
        try:
            return usage_id.name
        except AttributeError:
            # workaround for xblock workbench
            return usage_id

    @staticmethod
    def workbench_scenarios():
        """
        A canned scenario for display in the workbench.
        """
        return [("Drag-and-drop-v2 scenario", "<vertical_demo><drag-and-drop-v2/></vertical_demo>")]
