"""Strict primitive validation helpers."""
def required_string(value,name,max_length=255):
 if not isinstance(value,str) or not value.strip() or len(value)>max_length: raise ValueError(f"invalid_{name}")
 return value.strip()
def positive_int(value,name):
 try: number=int(value)
 except (TypeError,ValueError): raise ValueError(f"invalid_{name}")
 if number<=0: raise ValueError(f"invalid_{name}")
 return number
