// Model-written research orchestration body for ResearchProgramRunner.
// All command names must be explicitly registered and budgeted by the host.
// The same program ID must always refer to the same source digest.
const candidate = await host("candidate-001", "propose_conjecture", {
  problem_id: "REPLACE_WITH_CANONICAL_PROBLEM_ID",
  constraints: ["state assumptions", "do not claim formal verification"]
});
const review = await host("review-001", "review_candidate", {
  artifact_id: candidate.artifact_id
});
return {
  candidate_artifact_id: candidate.artifact_id,
  review_artifact_id: review.artifact_id,
  status: "awaiting_independent_verification"
};
