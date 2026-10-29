# AWS CodePipeline Centralized Email & Log Notifier

A robust, serverless AWS Lambda solution that captures **AWS CodePipeline** execution state changes (`STARTED`, `SUCCEEDED`, `FAILED`, `CANCELED`), extracts granular failure stack traces and script log outputs (including CodeDeploy instance log tails and CodeBuild compiler errors), and routes professional HTML-formatted email alerts via **Amazon SES** based on project naming conventions.

---

## Table of Contents

- [Features](#features)
- [Customizing Projects and Recipients](#customizing-projects-and-recipients)
- [Create `iam-policy.json` in the Repository](#create-iam-policyjson-in-the-repository)
- [A-to-Z Setup Instructions](#a-to-z-setup-instructions)
  - [Step 1: Configure Amazon SES](#step-1-configure-amazon-ses)
  - [Step 2: Create the Lambda IAM Role](#step-2-create-the-lambda-iam-role)
  - [Step 3: Deploy the Lambda Function](#step-3-deploy-the-lambda-function)
  - [Step 4: Configure Amazon EventBridge Rule (Single Region)](#step-4-configure-amazon-eventbridge-rule-single-region)
  - [Step 5: Multi-Region Event Centralization (Advanced)](#step-5-multi-region-event-centralization-advanced)

---

## Features

- **Multi-Action Log Extraction:**
  - **CodeBuild:** Automatically pulls failure stack traces and build outputs via CloudWatch Log tailing.
  - **CodeDeploy:** Extracts instance lifecycle script failures, exit codes, and stdout/stderr log tails (`logTail`).
  - **Source/Generic:** Pulls direct action error messages and summaries.
- **Dark-Themed Error Output:** Formats logs inside clean `<pre>` code blocks for optimal readability in email clients.
- **Multi-Project & Dynamic Recipient Routing:** Automatically inspects pipeline names and routes alerts to different specialized team distribution lists depending on the project keywords.
- **Idempotency Guard:** Built-in warm-container memory cache to block rapid duplicate events and prevent redundant notification spam.

---

## Customizing Projects and Recipients

Inside `lambda_function.py`, you can easily configure multiple projects and their respective recipient lists by editing these variables:

```python
# Default fallback email for general/unmatched pipelines
DEFAULT_RECIPIENTS = ["tech-ops@yourdomain.com"]

# Specific recipient group for AI / Specialized projects
SPECIALIZED_TEAM_RECIPIENTS = [
    "engineer1@yourdomain.com",
    "engineer2@yourdomain.com",
    "lead@yourdomain.com"
]

# Keywords used to match pipeline names (case-insensitive)
SPECIALIZED_PIPELINE_KEYWORDS = ["ai", "model", "llm", "crai"]
```

Anyone deploying this system can add, remove, or modify project keywords and email addresses to match their own infrastructure organization.

---

## Create `iam-policy.json` in the Repository

Back on your main repository page, click **Add file** again → **Create new file**.

1. In the file name box at the top, type:

   ```text
   iam-policy.json
   ```

2. Copy the IAM JSON policy block below and paste it into the editor box:

   ```json
   {
       "Version": "2012-10-17",
       "Statement": [
           {
               "Sid": "CodePipelineAndBuildPermissions",
               "Effect": "Allow",
               "Action": [
                   "codepipeline:ListActionExecutions",
                   "codebuild:BatchGetBuilds",
                   "logs:GetLogEvents"
               ],
               "Resource": "*"
           },
           {
               "Sid": "CodeDeployDetailedPermissions",
               "Effect": "Allow",
               "Action": [
                   "codedeploy:GetDeployment",
                   "codedeploy:ListDeploymentInstances",
                   "codedeploy:GetDeploymentInstance"
               ],
               "Resource": "*"
           },
           {
               "Sid": "SESEmailPermissions",
               "Effect": "Allow",
               "Action": [
                   "ses:SendEmail",
                   "ses:SendRawEmail"
               ],
               "Resource": "*"
           }
       ]
   }
   ```

3. Scroll down, click **Commit changes...**, and save.

---

## A-to-Z Setup Instructions

### Step 1: Configure Amazon SES

1. Open the **Amazon SES Console**.
2. Verify your **sender email address** (e.g., `no-reply@yourdomain.com`) and required **recipient emails/domains**.
3. If SES is in the **Sandbox environment**, ensure all recipient addresses are verified.

---

### Step 2: Create the Lambda IAM Role

1. Open the **IAM Console** → **Roles** → **Create role**.
2. Choose **AWS service** → **Lambda**.
3. Attach an inline policy using the contents of the `iam-policy.json` file created above.
4. Name the role `codepipeline-notifier-lambda-role`.

---

### Step 3: Deploy the Lambda Function

1. Open the **AWS Lambda Console** → **Create function**.
2. Choose **Author from scratch**:
   - **Function name:** `codepipeline-email-notifier`
   - **Runtime:** `Python 3.10+`
   - **Execution role:** *Use existing role* → `codepipeline-notifier-lambda-role`
3. Paste the code from `lambda_function.py` into the editor and click **Deploy**.
4. Under **Configuration** → **General configuration**, set the **Timeout** to `15 seconds`.

---

### Step 4: Configure Amazon EventBridge Rule (Single Region)

1. Open the **Amazon EventBridge Console** → **Rules** → **Create rule**.
2. Name the rule (e.g., `all-codepipelines-notification-rule`) and choose **Rule with an event pattern**.
3. Use this event pattern:

```json
{
  "source": ["aws.codepipeline"],
  "detail-type": ["CodePipeline Pipeline Execution State Change"],
  "detail": {
    "state": ["STARTED", "SUCCEEDED", "FAILED", "CANCELED"]
  }
}
```

4. Under **Target(s)**, select **AWS service** → **Lambda function**, and select your `codepipeline-email-notifier` function.
5. Save the rule.

---

### Step 5: Multi-Region Event Centralization (Advanced)

If your CodePipeline instances run across multiple auxiliary AWS regions (e.g., `us-west-1`, `us-east-2`) but you want all notifications centralized in a single **home region** (e.g., `us-east-1`):

1. **Configure Central Bus Policy (`us-east-1`):** Ensure your central event bus permits `events:PutEvents` from your source regions/accounts.

2. **Create Forwarding Rules in Source Regions (e.g., `us-west-1`):**
   - Open **EventBridge** in the source region → **Rules** → **Create rule**.
   - Use this event pattern:

     ```json
     {
       "source": ["aws.codepipeline"],
       "detail-type": ["CodePipeline Pipeline Execution State Change"]
     }
     ```

   - **Target:** Select **EventBridge event bus**, and paste the ARN of your central event bus in `us-east-1`.

3. **Grant the required IAM permissions** for cross-region event publishing (`events:PutEvents`).