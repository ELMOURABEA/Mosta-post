"""Reads a platform verdict and the verdict a source's own stack produced for the same check,
and says whether they agree.

Every source adopts the platform by evaluating in parallel while the product's own stack keeps
notifying. That posture is only worth its query cost if something reads both verdicts. This
package is that reader's contract and its classifier; a source supplies its own half.
"""
