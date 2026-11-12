"""Persistent observer/recovery dispatcher; no model calls in the daemon."""
import time
from workflow_common import rpc

def main():
    while True:
        try:rpc('generation_workflow_poll')
        except (OSError,ValueError,RuntimeError):pass
        time.sleep(3)

if __name__=='__main__':main()
