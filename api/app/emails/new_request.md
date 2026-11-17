---
version: new-request-v1
---

## subject

Access request: {{name}} ({{organization}})

## text

A new request for access to TrialMatch Rx.

Name: {{name}}
Email: {{email}}
Organization: {{organization}}
Role: {{role}}

Message:
{{message}}

Grant or dismiss it at {{admin_url}}. Replying to this email writes to the requester.

## html

<p>A new request for access to TrialMatch Rx.</p>
<table>
<tr><td>Name</td><td>{{name}}</td></tr>
<tr><td>Email</td><td>{{email}}</td></tr>
<tr><td>Organization</td><td>{{organization}}</td></tr>
<tr><td>Role</td><td>{{role}}</td></tr>
</table>
<p>Message:<br>
{{message}}</p>
<p>Grant or dismiss it at <a href="{{admin_url}}">{{admin_url}}</a>. Replying to this email writes to the requester.</p>
