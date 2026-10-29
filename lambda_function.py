import json
import re
import boto3
import time

ses_client = boto3.client('ses', region_name='us-east-1')

SENDER_EMAIL = "no-reply@utopiadeals.com"

# Default fallback team email
DEFAULT_RECIPIENTS = ["tech-ops@yourdomain.com"]

# Specific recipient group for AI / Specialized projects
SPECIALIZED_TEAM_RECIPIENTS = [
    "engineer1@yourdomain.com",
    "engineer2@yourdomain.com",
    "lead@yourdomain.com"
]

# Keywords used to match pipeline names (case-insensitive)
SPECIALIZED_PIPELINE_KEYWORDS = ["ai", "model", "llm", "crai"]
UUID_REGEX = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)

PROCESSED_EXECUTIONS = {}

def is_duplicate_event(execution_id, state):
    if not execution_id or execution_id == 'N/A':
        return False
    key = f"{execution_id}_{state}"
    now = time.time()
    
    expired = [k for k, t in PROCESSED_EXECUTIONS.items() if now - t > 600]
    for k in expired:
        del PROCESSED_EXECUTIONS[k]
        
    if key in PROCESSED_EXECUTIONS:
        return True
        
    PROCESSED_EXECUTIONS[key] = now
    return False

def get_target_recipients(pipeline_name):
    pipeline_lower = pipeline_name.lower()
    if any(keyword in pipeline_lower for keyword in AI_PIPELINE_KEYWORDS):
        return AI_RECIPIENTS
    return DEFAULT_RECIPIENTS

def clean_html(text):
    if not text:
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "'")

def fetch_codebuild_logs(external_id, region):
    try:
        codebuild_client = boto3.client('codebuild', region_name=region)
        logs_client = boto3.client('logs', region_name=region)
        
        build_id = external_id.split('/')[-1] if '/' in external_id else external_id
        build_info = codebuild_client.batch_get_builds(ids=[build_id])
        
        logs_info = build_info['builds'][0].get('logs', {})
        group_name = logs_info.get('groupName')
        stream_name = logs_info.get('streamName')
        
        if group_name and stream_name:
            response = logs_client.get_log_events(
                logGroupName=group_name,
                logStreamName=stream_name,
                limit=60,
                startFromHead=False
            )
            events = response.get('events', [])
            log_messages = [e['message'] for e in events]
            return "\n".join(log_messages) if log_messages else "Log stream was empty."
            
    except Exception as e:
        return f"Could not fetch CodeBuild CloudWatch logs: {str(e)}"
    return "No CloudWatch logs found for this build."

def fetch_codedeploy_details(external_id, region):
    try:
        codedeploy_client = boto3.client('codedeploy', region_name=region)
        deployment_id = external_id.split(':')[-1] if ':' in external_id else external_id
        
        deployment_info = codedeploy_client.get_deployment(deploymentId=deployment_id)
        info = deployment_info.get('deploymentInfo', {})
        
        error_info = info.get('errorInformation', {})
        error_code = error_info.get('code', 'UnknownCode')
        error_message = error_info.get('message', 'No message provided.')
        
        base_msg = f"CodeDeploy Deployment ID: {deployment_id}\nError Code: {error_code}\nReason: {error_message}"
        
        instances_response = codedeploy_client.list_deployment_instances(deploymentId=deployment_id)
        instance_ids = instances_response.get('instancesList', [])
        
        if not instance_ids:
            return base_msg
            
        instance_logs = []
        for inst_id in instance_ids:
            inst_detail = codedeploy_client.get_deployment_instance(
                deploymentId=deployment_id,
                instanceId=inst_id
            )
            instance_summary = inst_detail.get('instanceSummary', {})
            lifecycle_events = instance_summary.get('lifecycleEvents', [])
            
            for event in lifecycle_events:
                status = str(event.get('status', '')).upper()
                if status in ['FAILED', 'SKIPPED']:
                    event_name = event.get('lifecycleEventName', 'UnknownEvent')
                    diag = event.get('diagnostics', {})
                    script_name = diag.get('scriptName', 'N/A')
                    message = diag.get('message', '')
                    log_tail = diag.get('logTail', '')
                    script_output = log_tail if log_tail else message
                    
                    instance_logs.append(
                        f"\n--- Instance Failure [{inst_id}] ---"
                        f"\nLifecycle Event: {event_name}"
                        f"\nScript: {script_name}"
                        f"\nStatus Message: {message}"
                        f"\n\nScript Log Output:\n{script_output}"
                    )
        
        if instance_logs:
            return base_msg + "\n" + "\n".join(instance_logs)
            
        return base_msg
        
    except Exception as e:
        return f"Could not fetch CodeDeploy details: {str(e)}"

def get_pipeline_failure_details(pipeline_name, region, execution_id):
    try:
        codepipeline_client = boto3.client('codepipeline', region_name=region)
        failed_logs = []
        seen_messages = set()

        if execution_id and execution_id != 'N/A' and UUID_REGEX.match(execution_id):
            action_execs = codepipeline_client.list_action_executions(
                pipelineName=pipeline_name,
                filter={'pipelineExecutionId': execution_id}
            ).get('actionExecutionDetails', [])
            
            for action in action_execs:
                status = str(action.get('status', '')).upper()
                if status in ['FAILED', 'CANCELED']:
                    stage_name = action.get('stageName', 'Unknown Stage')
                    action_type = action.get('actionName', 'Unknown Action')
                    
                    output_info = action.get('output', {})
                    external_id = output_info.get('executionResult', {}).get('externalExecutionId', '')
                    
                    if external_id and ('codebuild' in external_id.lower() or '/' in external_id or len(external_id) > 20) and 'd-' not in external_id.lower():
                        build_logs = fetch_codebuild_logs(external_id, region)
                        log_entry = f"Stage: {stage_name} | Action: {action_type}\n\n{build_logs}"
                    elif external_id and ('codedeploy' in external_id.lower() or external_id.startswith('d-')):
                        deploy_logs = fetch_codedeploy_details(external_id, region)
                        log_entry = f"Stage: {stage_name} | Action: {action_type}\n\n{deploy_logs}"
                    else:
                        error_details = action.get('errorDetails', {})
                        error_message = error_details.get('message', '')
                        summary = action.get('summary', '')
                        error_text = error_message if error_message else (summary if summary else "Action failed without specific error message.")
                        log_entry = f"Stage: {stage_name} | Action: {action_type}\nError: {error_text}"
                    
                    if log_entry not in seen_messages:
                        seen_messages.add(log_entry)
                        failed_logs.append(log_entry)
            
            if failed_logs:
                return "\n\n".join(failed_logs)

        state = codepipeline_client.get_pipeline_state(name=pipeline_name)
        for stage in state.get('stageStates', []):
            stage_name = stage.get('stageName', '')
            for action in stage.get('actionStates', []):
                latest_exec = action.get('latestExecution', {})
                if str(latest_exec.get('status', '')).upper() in ['FAILED', 'CANCELED']:
                    action_type = action.get('actionName', '')
                    external_id = latest_exec.get('externalExecutionId', '')
                    
                    if external_id and ('codebuild' in external_id.lower() or '/' in external_id):
                        build_logs = fetch_codebuild_logs(external_id, region)
                        log_entry = f"Stage: {stage_name} | Action: {action_type}\n\n{build_logs}"
                    elif external_id and ('codedeploy' in external_id.lower() or external_id.startswith('d-')):
                        deploy_logs = fetch_codedeploy_details(external_id, region)
                        log_entry = f"Stage: {stage_name} | Action: {action_type}\n\n{deploy_logs}"
                    else:
                        error_details = latest_exec.get('errorDetails', {})
                        error_message = error_details.get('message', 'Action failed.')
                        log_entry = f"Stage: {stage_name} | Action: {action_type}\nError: {error_message}"
                    
                    if log_entry not in seen_messages:
                        seen_messages.add(log_entry)
                        failed_logs.append(log_entry)

        return "\n\n".join(failed_logs) if failed_logs else "Pipeline failed, but no specific action execution details were returned."

    except Exception as e:
        return f"Unable to inspect pipeline failure state: {str(e)}"

def lambda_handler(event, context):
    try:
        print(f"RAW_INCOMING_EVENT: {json.dumps(event)}")
        
        detail_type = event.get('detail-type', '')
        if detail_type != "CodePipeline Pipeline Execution State Change":
            return {'statusCode': 200}

        detail = event.get('detail', {})
        pipeline_name = detail.get('pipeline', 'Unknown-Pipeline')
        state = detail.get('state', 'UNKNOWN')
        execution_id = detail.get('execution-id', 'N/A')
        region = event.get('region', 'us-east-1')

        if is_duplicate_event(execution_id, state):
            print(f"Duplicate event blocked for execution {execution_id} ({state}).")
            return {'statusCode': 200}

        recipients = get_target_recipients(pipeline_name)

        if state == 'STARTED':
            subject = f"[STARTED] {pipeline_name} ({region})"
            body = f"<div style='font-family: Arial, sans-serif;'><h3 style='color: #0275d8;'>Pipeline Execution Started</h3><p>Pipeline <b>{pipeline_name}</b> has started in region <b>{region}</b>.</p></div>"
            ses_client.send_email(Source=SENDER_EMAIL, Destination={'ToAddresses': recipients}, Message={'Subject': {'Data': subject}, 'Body': {'Html': {'Data': body}}})

        elif state == 'SUCCEEDED':
            subject = f"[SUCCESS] {pipeline_name} ({region})"
            body = f"<div style='font-family: Arial, sans-serif;'><h3 style='color: #5cb85c;'>Pipeline Execution Succeeded</h3><p>Pipeline <b>{pipeline_name}</b> completed all stages in region <b>{region}</b>.</p></div>"
            ses_client.send_email(Source=SENDER_EMAIL, Destination={'ToAddresses': recipients}, Message={'Subject': {'Data': subject}, 'Body': {'Html': {'Data': body}}})

        elif state in ['FAILED', 'CANCELED']:
            subject = f"[FAILED] {pipeline_name} ({region})"
            log_output = get_pipeline_failure_details(pipeline_name, region, execution_id)
            clean_log = clean_html(log_output)
            
            body = f"""
            <div style='font-family: Arial, sans-serif;'>
                <h3 style='color: #d9534f;'>Pipeline Execution Failed</h3>
                <p>Pipeline <b>{pipeline_name}</b> encountered a failure in region <b>{region}</b>.</p>
                <p style='font-size: 12px; color: #666;'>Execution ID: {execution_id}</p>
                <h4>Failure Details & Output:</h4>
                <pre style='background: #1e1e1e; color: #f8f8f2; padding: 15px; border-radius: 5px; font-family: Consolas, Monaco, monospace; font-size: 13px; line-height: 1.5; overflow-x: auto;'>{clean_log}</pre>
            </div>
            """
            ses_client.send_email(Source=SENDER_EMAIL, Destination={'ToAddresses': recipients}, Message={'Subject': {'Data': subject}, 'Body': {'Html': {'Data': body}}})

        return {'statusCode': 200}

    except Exception as e:
        print(f"Error handling event: {str(e)}")
        return {'statusCode': 200}