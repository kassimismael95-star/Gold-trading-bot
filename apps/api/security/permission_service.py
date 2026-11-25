"""Ownership and role policy helpers shared by route modules."""
def owns_account(user,account): return bool(user and account and account.owner_id==user.id)
def is_admin(user): return bool(user and user.role=="admin")
def require_owner_or_admin(user,account): return is_admin(user) or owns_account(user,account)
