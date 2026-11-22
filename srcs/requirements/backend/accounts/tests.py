from django.core import mail
from django.test import Client, TestCase

from .models import LoginCode, Organization, Role, User


class SignUpEmailTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(code="o", name="GA Berlin")
        self.manager = User.objects.create_user(
            email="resp@demo.test", organization=self.organization, role=Role.MANAGER, is_approved=True
        )
        User.objects.create_user(email="aguerri@demo.test", organization=self.organization, role=Role.EXPERIENCED, is_approved=True)
        User.objects.create_superuser(email="admin@demo.test")

    def sign_up(self, email="new@demo.test", organization=None):
        _, code, _ = LoginCode.issue(email, organization or self.organization)
        response = Client().post("/api/auth/login/code/", {"email": email, "code": code}, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)

    def test_new_sign_up_emails_the_responsables(self):
        self.sign_up()
        self.assertEqual([m.to for m in mail.outbox], [["resp@demo.test"]])
        self.assertIn("new@demo.test", mail.outbox[0].body)

    def test_logging_in_again_while_pending_does_not_email_again(self):
        self.sign_up()
        self.sign_up()
        self.assertEqual(len(mail.outbox), 1)

    def test_without_responsable_the_site_admins_are_emailed(self):
        other = Organization.objects.create(code="p", name="GA Leipzig")
        self.sign_up(organization=other)
        self.assertEqual([m.to for m in mail.outbox], [["admin@demo.test"]])

    def test_approval_emails_the_member(self):
        self.sign_up()
        member = User.objects.get(email="new@demo.test")
        mail.outbox.clear()
        client = Client()
        client.force_login(self.manager)
        url = f"/api/manage/members/{member.pk}/"
        self.assertEqual(client.patch(url, {"is_approved": True}, content_type="application/json").status_code, 200)
        self.assertEqual([m.to for m in mail.outbox], [["new@demo.test"]])
        self.assertIn("validé", mail.outbox[0].subject)

        # Changing the role afterwards is not a new approval.
        client.patch(url, {"role": Role.EXPERIENCED}, content_type="application/json")
        self.assertEqual(len(mail.outbox), 1)
