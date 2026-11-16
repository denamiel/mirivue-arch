"""Automatic publishing requires increasing versions, trusted main and validated installation."""
from pathlib import Path
import re
import unittest

WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/repository.yml'


def job_block(text, name):
    lines = text.splitlines()
    start = lines.index(f'  {name}:')
    block = []
    for line in lines[start + 1:]:
        if re.match(r'^  \S', line):
            break
        block.append(line)
    return block


def job_value(block, key):
    """Read "key: value" or a folded "key: >-" value at job level (4 spaces)."""
    for index, line in enumerate(block):
        match = re.match(rf'^    {key}:\s*(.*)$', line)
        if not match:
            continue
        value = match.group(1).strip()
        if value in ('>-', '>', '|', '|-'):
            folded = []
            for following in block[index + 1:]:
                if not following.startswith('      '):
                    break
                folded.append(following.strip())
            value = ' '.join(folded)
        return value
    return None


def evaluate(condition, context):
    """Restricted evaluator: "x == 'v'" / "x != 'v'" terms joined by && only."""
    text = ' '.join(condition.replace('${{', '').replace('}}', '').split())
    if '||' in text or re.search(r'!(?!=)', text) or '(' in text:
        raise AssertionError(f'condition non restreinte : {text}')
    result = True
    for term in text.split('&&'):
        match = re.fullmatch(r"\s*([\w.]+)\s*(==|!=)\s*'([^']*)'\s*", term)
        if not match:
            raise AssertionError(f'terme non pris en charge : {term!r}')
        name, operator, value = match.groups()
        actual = context.get(name, '')
        result = result and ((actual == value) if operator == '==' else (actual != value))
    return result


class PublicationControleeTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding='utf-8')
        self.publish = job_block(self.text, 'publish')
        self.condition = job_value(self.publish, 'if')

    def context(self, **values):
        base = {'vars.PUBLISH_ENABLED': 'true', 'github.ref': 'refs/heads/main'}
        base.update(values)
        return base

    def test_only_main_with_a_new_validated_version_can_publish(self):
        for ref, ready, expected in [('refs/heads/main','true',True),('refs/heads/main','false',False),
                                     ('refs/pull/1/merge','true',False),('refs/heads/dev','true',False)]:
            with self.subTest(ref=ref,ready=ready):
                self.assertEqual(evaluate(self.condition,{'github.ref':ref,'needs.plan.outputs.publish':ready}),expected)

    def test_publish_uses_environment_and_full_installation_gate(self):
        self.assertEqual(job_value(self.publish,'environment'),'publication-pacman')
        self.assertIn('qualification',job_value(self.publish,'needs'))
        self.assertIn('assert_publication_context', (WORKFLOW.parents[2]/'scripts/repository.py').read_text())

    def test_setup_script_never_requests_a_publication(self):
        script = (WORKFLOW.parents[2] / 'Configurer-publication-GitHub.sh').read_text(encoding='utf-8')
        executed = [line for line in script.splitlines()
                    if re.match(r'^\s*gh workflow run\b', line)]
        self.assertEqual(executed, [], 'le script de configuration ne doit jamais lancer de publication')
        self.assertIn('environments/publication-pacman', script)

    def test_only_publish_job_writes_releases(self):
        for job in re.findall(r'(?m)^  ([\w-]+):\s*$', self.text.split('\njobs:\n', 1)[1]):
            block = '\n'.join(job_block(self.text, job))
            if re.search(r'gh release (upload|create|edit|delete-asset)|git push', block):
                with self.subTest(job=job):
                    self.assertEqual(job, 'publish')


if __name__ == '__main__':
    unittest.main()
