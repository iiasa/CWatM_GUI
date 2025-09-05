#!/usr/bin/env python3
"""
CWatM Subprocess Runner - Isolated CWatM execution script
This script runs CWatM in a separate process to prevent crashes from affecting the main GUI
"""

import sys
import json
import traceback
import os

def run_cwatm_isolated(config_file, args, output_file):
    """Run CWatM in isolated environment and capture all output"""
    
    try:
        # Import CWatM modules
        import cwatm.run_cwatm as run_cwatm
        from cwatm.management_modules.globals import calibclear
        
        # Capture all output
        output_data = {
            'success': False,
            'last_dis': None,
            'output': [],
            'error': None
        }
        
        # Custom print capture
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        
        class OutputCapture:
            def __init__(self, output_list, is_error=False):
                self.output_list = output_list
                self.is_error = is_error
                
            def write(self, text):
                if text.strip():
                    self.output_list.append({
                        'text': text.strip(),
                        'is_error': self.is_error
                    })
                    
            def flush(self):
                pass
        
        # Redirect output
        stdout_capture = OutputCapture(output_data['output'], False)
        stderr_capture = OutputCapture(output_data['output'], True)
        sys.stdout = stdout_capture
        sys.stderr = stderr_capture
        
        # Validate config file exists before attempting to run
        if not os.path.exists(config_file):
            raise FileNotFoundError(f"Configuration file not found: {config_file}")
            
        # Execute CWatM
        print(f"Starting CWatM execution with config: {config_file}")
        success, last_dis = run_cwatm.mainwarm(config_file, args, None)
        
        output_data['success'] = success
        output_data['last_dis'] = str(last_dis) if last_dis is not None else None
        
        print(f"CWatM execution completed: success={success}")
        
    except Exception as e:
        # Capture any errors
        output_data['error'] = f"CWatM execution failed: {str(e)}"
        output_data['traceback'] = traceback.format_exc()
        print(f"ERROR: {str(e)}", file=sys.stderr)
        
    finally:
        # Restore original stdout/stderr
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        
        # Clean up
        try:
            calibclear()
        except:
            pass
            
        # Write results to file
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2)
        except Exception as e:
            print(f"Failed to write output file: {e}", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: cwatm_subprocess_runner.py <config_file> <args_json> <output_file>")
        sys.exit(1)
        
    config_file = sys.argv[1]
    args_json = sys.argv[2]
    output_file = sys.argv[3]
    
    # Parse arguments
    try:
        args = json.loads(args_json)
    except:
        args = []
    
    # Run CWatM
    run_cwatm_isolated(config_file, args, output_file)