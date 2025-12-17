import socket
from PyQt5 import QtCore
import runpod
import time
import requests
import urllib3
from utils import Chat
class LLMWorker(QtCore.QThread):
    tokenReceived = QtCore.pyqtSignal(str)
    statusChanged = QtCore.pyqtSignal(str)
    errorOccurred = QtCore.pyqtSignal(str)

    def __init__(self, chat:Chat ,endpoint: runpod.Endpoint, MAX_TOKEN_length: int, parent=None):
        super().__init__(parent)
        self.chat = chat
        self.endpoint = endpoint
        self.MAX_TOKEN_LENGTH = MAX_TOKEN_length 
        self._run_request = None

    def cancel(self):
        """Cancel an active run_request if present and request thread interruption."""
        try:
            if getattr(self, '_run_request', None):
                try:
                    self._run_request.cancel()
                except Exception:
                    pass
        finally:
            try:
                # ask the thread to stop (checked in run loop)
                self.requestInterruption()
            except Exception:
                pass

    def run(self):
        socket.setdefaulttimeout(600)
        
        # Build system message
        system_msg = f"You are a helpful assistant. You are expected to answer within {self.MAX_TOKEN_LENGTH} tokens. Make your answers concise and to the point. If the user provides documents, use them to inform your response. If no documents are provided, answer based on your training data. If the user asks for code, provide only the code without additional explanations. Your last token should be a newline character."
        
        messages = [{"role": "system", "content": system_msg}]
        
        # Add all messages from chat history (should at least have one user message)
        if self.chat and hasattr(self.chat, 'messages') and self.chat.messages:
            for msg in self.chat.messages:
                if msg and hasattr(msg, 'role') and hasattr(msg, 'content'):
                    role = str(msg.role).lower().strip() if msg.role else "user"
                    content = str(msg.content).strip() if msg.content else ""
                    if content:  # Only add if content is non-empty
                        messages.append({
                            "role": role,
                            "content": content
                        })
        
        # Validate we have at least system + user message
        if len(messages) < 2:
            self.errorOccurred.emit("No messages to send to endpoint")
            self.statusChanged.emit("Error")
            return
            
        payload = {
            "input": {
                "messages": messages,
                "sampling_params": {"temperature": 0.6, "max_tokens": self.MAX_TOKEN_LENGTH},
                "policy": {"executionTimeout": 900000, "ttl": 3600000},
            }
        }
        
        print(f"Payload prepared: {payload}")
        try:
            print("Sending payload to endpoint...")
            # store request so it can be cancelled from another thread
            self._run_request = self.endpoint.run(payload)
            run_request = self._run_request
            print(f"Endpoint returned: {run_request}")
            is_completed = False
            try:
                response_buffer = ""
                while not is_completed:
                    # allow graceful interruption
                    if self.isInterruptionRequested():
                        print("Interruption requested, cancelling run_request...")
                        try:
                            if run_request:
                                run_request.cancel()
                        except Exception:
                            pass
                        break

                    status = run_request.status()
                    print(f"Current job status: {status}")

                    if status == "COMPLETED":
                        is_completed = True
                        output = run_request.output()
                        if isinstance(output, dict):
                            text = output.get("choices", "")[0].get('tokens', '')
                        else:
                            print(f"Output is a {type(output)}.")
                            text = output[0].get("choices", "")[0].get('tokens', '')
                        if text:
                            response_buffer += ''.join(text)
                            if response_buffer is list:
                                response_buffer = ''.join(response_buffer)
                            self.tokenReceived.emit(response_buffer)
                            print("Job output:", output)
                            break
                    elif status == "IN_QUEUE":
                        print("Job is still in queue. Waiting...")
                        self.statusChanged.emit("In Queue")
                    elif status in ["FAILED", "ERROR"]:
                        print("Job failed to complete successfully.")
                        self.errorOccurred.emit("Job failed to complete successfully.")
                        self.statusChanged.emit("Error")
                        break
                    else:
                        time.sleep(10)
            except KeyboardInterrupt:  # Catch KeyboardInterrupt
                print("KeyboardInterrupt detected. Canceling the job...")
                if getattr(self, '_run_request', None):  # Check if a job is active
                    try:
                        self._run_request.cancel()
                        print("Job canceled.")
                    except Exception:
                        pass
                
            except (requests.exceptions.ReadTimeout, urllib3.exceptions.ReadTimeoutError) as e:
                msg = f"Stream read timeout: {e}"
                print(msg)
                self.errorOccurred.emit(msg)
                self.statusChanged.emit("Completed (timeout)")
            except Exception as e:
                msg = f"Stream error: {e}"
                print(msg)
                self.errorOccurred.emit(msg)
                self.statusChanged.emit("Error")
            else:
                self.statusChanged.emit("Completed")
        except Exception as e:
            msg = f"Run request error: {e}"
            print(msg)
            self.errorOccurred.emit(msg)
            self.statusChanged.emit("Error")
        finally:
            # clear stored run request reference
            try:
                self._run_request = None
            except Exception:
                pass