from pathlib import Path

app_name = "frappe_scenario"
app_title = "Frappe Scenario"
app_publisher = "Agathodaemon"
app_description = "Deterministic, AI-operable synthetic scenario data generation for Frappe and ERPNext"
app_email = "agatho_daemon@icloud.com"
app_license = "gpl-3.0"

# Scenario providers
# ------------------
# Providers are discovered through this hook, so any app may contribute one
# without this app knowing about it. Order here is irrelevant: execution order
# comes from the declared capability dependencies.
scenario_providers = [
	"frappe_scenario.providers.frappe_settings.FrappeFoundationProvider",
	"frappe_scenario.providers.erpnext_foundation.ErpnextFoundationProvider",
	"frappe_scenario.providers.erpnext_parties.ErpnextPartiesProvider",
	"frappe_scenario.providers.erpnext_catalog.ErpnextCatalogProvider",
	"frappe_scenario.providers.erpnext_opening.ErpnextOpeningProvider",
	"frappe_scenario.providers.erpnext_commercial.ErpnextCommercialProvider",
	"frappe_scenario.providers.erpnext_buying.ErpnextBuyingProvider",
	"frappe_scenario.providers.erpnext_selling.ErpnextSellingProvider",
	"frappe_scenario.providers.erpnext_payments.ErpnextPaymentsProvider",
]

# AI adapters translate trusted, structured Scenario inputs into provider
# requests. They never execute model output or create ERPNext documents.
scenario_ai_adapters = [
	"frappe_scenario.ai.openai.OpenAIAdapter",
]

# Apps
# ------------------

# Frappe resolves unknown plain dependency names through an online repository
# lookup before ``before_install`` runs. Declare ERPNext when its checkout is
# present; otherwise the install guard below stops with explicit recovery steps.
_erpnext_checkout = Path(__file__).resolve().parents[2] / "erpnext"
required_apps = ["erpnext"] if _erpnext_checkout.is_dir() else []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "frappe_scenario",
# 		"logo": "/assets/frappe_scenario/logo.png",
# 		"title": "Frappe Scenario",
# 		"route": "/frappe_scenario",
# 		"has_permission": "frappe_scenario.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/frappe_scenario/css/frappe_scenario.css"
app_include_js = "/assets/frappe_scenario/js/tutorial_runner.js"

# include js, css files in header of web template
# web_include_css = "/assets/frappe_scenario/css/frappe_scenario.css"
# web_include_js = "/assets/frappe_scenario/js/frappe_scenario.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "frappe_scenario/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "frappe_scenario/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "frappe_scenario.utils.jinja_methods",
# 	"filters": "frappe_scenario.utils.jinja_filters"
# }

# Installation
# ------------

before_install = "frappe_scenario.install.before_install"
after_install = "frappe_scenario.install.after_install"
after_migrate = "frappe_scenario.core.learning.sync_learning_paths"

# Login
# -----

on_login = "frappe_scenario.onboarding.on_login"

# Uninstallation
# ------------

# before_uninstall = "frappe_scenario.uninstall.before_uninstall"
# after_uninstall = "frappe_scenario.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "frappe_scenario.utils.before_app_install"
# after_app_install = "frappe_scenario.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "frappe_scenario.utils.before_app_uninstall"
# after_app_uninstall = "frappe_scenario.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "frappe_scenario.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"frappe_scenario.tasks.all"
# 	],
# 	"daily": [
# 		"frappe_scenario.tasks.daily"
# 	],
# 	"hourly": [
# 		"frappe_scenario.tasks.hourly"
# 	],
# 	"weekly": [
# 		"frappe_scenario.tasks.weekly"
# 	],
# 	"monthly": [
# 		"frappe_scenario.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "frappe_scenario.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "frappe_scenario.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "frappe_scenario.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["frappe_scenario.utils.before_request"]
# after_request = ["frappe_scenario.utils.after_request"]

# Job Events
# ----------
# before_job = ["frappe_scenario.utils.before_job"]
# after_job = ["frappe_scenario.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"frappe_scenario.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []
