import logging
import aiohttp.web
import asab
import asab.web.rest
import asab.exceptions

from ....models.const import ResourceId
from ....decorators import access_control
from . import schema


L = logging.getLogger(__name__)


class RolesHandler(object):
	"""
	Assign or unassign roles

	---
	tags: ["Roles"]
	"""

	def __init__(self, app, role_svc):
		self.App = app
		self.RoleService = role_svc
		self.RBACService = app.get_service("seacatauth.RBACService")

		web_app = app.WebContainer.WebApp
		web_app.router.add_get("/roles/{tenant}/{credentials_id}", self.get_roles_by_credentials)
		web_app.router.add_put("/roles/{tenant}/{credentials_id}", self.set_roles)
		web_app.router.add_put("/roles/{tenant}", self.get_roles_batch)
		web_app.router.add_post("/role_assign/{credentials_id}/{tenant}/{role_name}", self.assign_role)
		web_app.router.add_delete("/role_assign/{credentials_id}/{tenant}/{role_name}", self.unassign_role)


	async def get_roles_by_credentials(self, request):
		"""
		Get credentials' roles
		"""
		creds_id = request.match_info["credentials_id"]
		tenant_id = request.match_info["tenant"]
		if tenant_id == "*" or request.can_access_all_tenants \
			or await self.RoleService.TenantService.has_tenant_assigned(request.Session.Credentials.Id, tenant_id):
			result = await self.RoleService.get_roles_by_credentials(creds_id, [tenant_id])
			return asab.web.rest.json_response(request, result)
		L.log(asab.LOG_NOTICE, "Tenant access denied.", struct_data={
			"cid": request.Session.Credentials.Id, "t": tenant_id})
		return aiohttp.web.HTTPForbidden()


	@asab.web.rest.json_schema_handler(schema.BATCH_GET_CREDENTIALS_ROLES)
	async def get_roles_batch(self, request, *, json_data):
		"""
		Get the assigned roles for several credentials
		"""
		tenant_id = request.match_info["tenant"]
		if tenant_id == "*" or request.can_access_all_tenants \
			or await self.RoleService.TenantService.has_tenant_assigned(request.Session.Credentials.Id, tenant_id):
			response = {
				cid: await self.RoleService.get_roles_by_credentials(cid, [tenant_id])
				for cid in json_data
			}
			return asab.web.rest.json_response(request, response)

		L.log(asab.LOG_NOTICE, "Tenant access denied.", struct_data={
			"cid": request.Session.Credentials.Id, "t": tenant_id})
		return aiohttp.web.HTTPForbidden()


	@asab.web.rest.json_schema_handler(schema.SET_CREDENTIALS_ROLES)
	@access_control(ResourceId.ROLE_ASSIGN)
	async def set_roles(self, request, *, json_data, tenant, resources):
		"""
		Set credentials' roles

		For given credentials ID, assign listed roles and unassign existing roles that are not in the list

		Cases:
		1) The requester is superuser AND requested `tenant` is "*":
			Only global roles will be un/assigned.
		2) The requester is superuser AND requested `tenant` is "tenant-name":
			Roles from "tenant-name/..." + global roles will be un/assigned.
		3) The requester is not superuser AND requested `tenant` is "tenant-name":
			Only "tenant-name/..." roles will be un/assigned.
		ELSE) In other cases the role assignment fails.
		"""
		credentials_id = request.match_info["credentials_id"]
		requested_roles = json_data["roles"]

		# Determine whether global roles will be un/assigned
		if ResourceId.SUPERUSER in resources:
			include_global = True
		elif tenant == "*":
			L.log(asab.LOG_NOTICE, "Not authorized to manage global roles.", struct_data={
				"cid": request.CredentialsId})
			return aiohttp.web.HTTPForbidden()
		else:
			include_global = False

		await self.RoleService.set_roles(credentials_id, requested_roles, tenant, include_global)

		return asab.web.rest.json_response(request, {"result": "OK"})


	@access_control(ResourceId.ROLE_ASSIGN)
	async def assign_role(self, request, *, tenant):
		"""
		Assign role to credentials
		"""
		role_id = "{}/{}".format(tenant, request.match_info["role_name"])
		if tenant == "*":
			# Assigning global roles requires superuser
			if not self.RBACService.is_superuser(request.Session.Authorization.Authz):
				message = "Missing permissions to un/assign global role"
				L.warning(message, struct_data={
					"agent_cid": request.Session.Credentials.Id,
					"role": role_id,
				})
				return asab.web.rest.json_response(
					request,
					data={
						"result": "FORBIDDEN",
						"message": message
					},
					status=403
				)

		await self.RoleService.assign_role(
			credentials_id=request.match_info["credentials_id"],
			role_id=role_id
		)

		return asab.web.rest.json_response(request, data={"result": "OK"})


	@access_control(ResourceId.ROLE_ASSIGN)
	async def unassign_role(self, request, *, tenant):
		"""
		Unassign role from credentials
		"""
		role_id = "{}/{}".format(tenant, request.match_info["role_name"])
		if tenant == "*":
			# Unassigning global roles requires superuser
			if not self.RBACService.is_superuser(request.Session.Authorization.Authz):
				message = "Missing permissions to un/assign global role"
				L.warning(message, struct_data={
					"agent_cid": request.Session.Credentials.Id,
					"role": role_id,
				})
				return asab.web.rest.json_response(
					request,
					data={
						"result": "FORBIDDEN",
						"message": message
					},
					status=403
				)

		await self.RoleService.unassign_role(
			credentials_id=request.match_info["credentials_id"],
			role_id=role_id
		)
		return asab.web.rest.json_response(request, data={"result": "OK"})
