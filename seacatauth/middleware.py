import aiohttp.web
import asab


def app_middleware_factory(app):

	@aiohttp.web.middleware
	async def app_middleware(request, handler):
		"""
		Add the application object to the request.
		"""
		request.App = app
		return await handler(request)

	return app_middleware


def api_auth_middleware_factory(app):
	oidc_service = app.get_service("seacatauth.OpenIdConnectService")
	require_authentication = asab.Config.getboolean("seacat:api", "require_authentication")
	authorization_resource = asab.Config.get("seacat:api", "authorization_resource")

	rbac_svc = app.get_service("seacatauth.RBACService")

	@aiohttp.web.middleware
	async def auth_middleware(request, handler):
		"""
		Authenticate and authorize all incoming requests.
		Raise HTTP 401 if authentication or authorization fails.
		"""
		try:
			# Authorize by OAuth Bearer token
			# (Authorization by cookie is not allowed for API access)
			request.Session = await oidc_service.get_session_from_authorization_header(request)
		except KeyError:
			request.Session = None

		def has_resource_access(tenant: str, resource: str) -> bool:
			return rbac_svc.has_resource_access(request.Session.Authz, tenant, [resource]) == "OK"

		request.has_resource_access = has_resource_access

		if require_authentication is False:
			return await handler(request)

		# All API endpoints are considered non-public and have to pass authn/authz
		if request.Session is not None:
			if authorization_resource == "DISABLED":
				return await handler(request)
			# Resource authorization is required: scan ALL THE RESOURCES
			#   for `authorization_resource` or "authz:superuser"
			resources = set(
				resource
				for roles in request.Session.Authz.values()
				for resources in roles.values()
				for resource in resources
			)
			# Grant access to superuser
			if "authz:superuser" in resources:
				return await handler(request)
			# Grant access the the bearer of `authorization_resource`
			if authorization_resource in resources:
				return await handler(request)

		raise aiohttp.web.HTTPUnauthorized()

	return auth_middleware


def public_auth_middleware_factory(app):
	oidc_service = app.get_service("seacatauth.OpenIdConnectService")
	cookie_service = app.get_service("seacatauth.CookieService")

	@aiohttp.web.middleware
	async def auth_middleware(request, handler):
		"""
		Try to authenticate before accessing public endpoints.
		"""
		# Authorize by OAuth Bearer token
		try:
			request.Session = await oidc_service.get_session_from_authorization_header(request)
		except KeyError:
			request.Session = None

		# Use cookie if Bearer token auth fails
		if request.Session is None:
			request.Session = await cookie_service.get_session_by_sci(request)

		return await handler(request)

	return auth_middleware
