import unittest
from workflow_jobs import attempt_limit

class Bound(unittest.TestCase):
    def test_only_the_same_documentary_gets_one_more_technical_continuation(self):
        job='51c0cfdb56e743d88c68859e5b6df165'
        self.assertEqual(attempt_limit('documentary',job),6)
        self.assertEqual(attempt_limit('documentary','other'),3)
        self.assertEqual(attempt_limit('catarsis',job),3)

if __name__=='__main__':unittest.main()
