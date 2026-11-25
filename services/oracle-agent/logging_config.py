"""Redacting logging filter for agent secrets."""
import logging
class RedactFilter(logging.Filter):
 def filter(self,record):
  message=str(record.getMessage())
  for key in ("password=","token=","secret="):
   if key in message: message=message.split(key,1)[0]+key+"[REDACTED]"
  record.msg=message; record.args=(); return True
