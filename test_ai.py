import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from analytics.facades import TrafficAnalyticsFacade

user, _ = User.objects.get_or_create(username="aitest", defaults={"password": "x"})
user.set_password("aitest123")
user.save()

c = Client()
c.login(username="aitest", password="aitest123")

with open("sample_data/access.log", "rb") as f:
    sf = SimpleUploadedFile("access.log", f.read())

facade = TrafficAnalyticsFacade()
lf = facade.upload_and_process(sf, name="access.log")
lf.user = user
lf.save(update_fields=["user"])

print(f"LogFile id={lf.pk}, user={lf.user}")

r = c.get(f"/logs/{lf.pk}/ai-analyze/")
print(f"Status: {r.status_code}")
print(f"Body: {r.content.decode()[:500]}")