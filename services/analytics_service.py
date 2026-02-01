"""
Analytics Service for BlueAI Assessment Platform
Provides student performance trends, assessment insights, and AI-generated recommendations
"""

from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
import statistics
# from emergentintegrations.llm.chat import UserMessage

class AnalyticsService:
    def __init__(self, db):
        self.db = db
    
    async def calculate_difficulty_index(self, assessment_id: str) -> float:
        """
        Calculate difficulty index for an assessment
        DifficultyIndex = 1 - (class_average / max_marks)
        Higher value = more difficult
        """
        # Get all marked attempts for this assessment
        attempts = await self.db.attempts.find({
            "assessment_id": assessment_id,
            "status": "marked"
        }, {"_id": 0, "score": 1}).to_list(1000)
        
        if not attempts:
            return 0.0
        
        # Get max marks from the question
        assessment = await self.db.assessments.find_one({"id": assessment_id}, {"_id": 0})
        if not assessment:
            return 0.0
        
        question = await self.db.questions.find_one({"id": assessment.get("question_id")}, {"_id": 0})
        if not question:
            return 0.0
        
        max_marks = question.get("max_marks", 100)
        scores = [a.get("score", 0) for a in attempts]
        class_average = statistics.mean(scores) if scores else 0
        
        difficulty_index = 1 - (class_average / max_marks) if max_marks > 0 else 0
        return round(difficulty_index, 3)
    
    async def calculate_student_trend(self, student_name: str, owner_teacher_id: str) -> Dict[str, Any]:
        """
        Calculate performance trend for a student based on last 3+ assessments
        Returns: improving / declining / stable
        """
        # Get student's last submissions ordered by date
        attempts = await self.db.attempts.find({
            "student_name": student_name,
            "owner_teacher_id": owner_teacher_id,
            "status": "marked"
        }, {"_id": 0}).sort("submitted_at", -1).to_list(10)
        
        if len(attempts) < 2:
            return {
                "trend": "insufficient_data",
                "slope": 0,
                "recent_scores": []
            }
        
        # Get scores with max marks for percentage calculation
        recent_scores = []
        for attempt in attempts[:5]:  # Last 5 for trend analysis
            assessment = await self.db.assessments.find_one({"id": attempt.get("assessment_id")}, {"_id": 0})
            if assessment:
                question = await self.db.questions.find_one({"id": assessment.get("question_id")}, {"_id": 0})
                max_marks = question.get("max_marks", 100) if question else 100
                score = attempt.get("score", 0)
                percentage = (score / max_marks * 100) if max_marks > 0 else 0
                recent_scores.append({
                    "score": score,
                    "max_marks": max_marks,
                    "percentage": round(percentage, 1),
                    "date": attempt.get("submitted_at")
                })
        
        # Calculate slope using simple linear regression
        if len(recent_scores) >= 2:
            # Reverse to get chronological order (oldest first)
            percentages = [s["percentage"] for s in reversed(recent_scores)]
            n = len(percentages)
            x_vals = list(range(n))
            x_mean = statistics.mean(x_vals)
            y_mean = statistics.mean(percentages)
            
            numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, percentages))
            denominator = sum((x - x_mean) ** 2 for x in x_vals)
            
            slope = numerator / denominator if denominator != 0 else 0
            
            # Determine trend based on slope
            if slope > 0.15:
                trend = "improving"
            elif slope < -0.15:
                trend = "declining"
            else:
                trend = "stable"
        else:
            slope = 0
            trend = "stable"
        
        return {
            "trend": trend,
            "slope": round(slope, 3),
            "recent_scores": recent_scores
        }
    
    async def check_needs_support(self, student_name: str, owner_teacher_id: str) -> Dict[str, Any]:
        """
        Determine if student needs support based on:
        - Average < 50% OR
        - Failed 2 of last 3 assessments OR
        - Declining performance trend
        """
        trend_data = await self.calculate_student_trend(student_name, owner_teacher_id)
        recent_scores = trend_data.get("recent_scores", [])
        
        if not recent_scores:
            return {"needs_support": False, "reasons": []}
        
        reasons = []
        
        # Check average
        percentages = [s["percentage"] for s in recent_scores]
        average = statistics.mean(percentages) if percentages else 0
        
        if average < 50:
            reasons.append(f"Average score below 50% ({round(average, 1)}%)")
        
        # Check last 3 assessments for failures
        last_3 = recent_scores[:3]
        failures = sum(1 for s in last_3 if s["percentage"] < 50)
        if failures >= 2:
            reasons.append(f"Failed {failures} of last 3 assessments")
        
        # Check declining trend
        if trend_data.get("trend") == "declining":
            reasons.append("Declining performance trend detected")
        
        return {
            "needs_support": len(reasons) > 0,
            "reasons": reasons,
            "average_percentage": round(average, 1),
            "trend": trend_data.get("trend"),
            "slope": trend_data.get("slope")
        }
    
    async def get_topic_performance(self, owner_teacher_id: str) -> List[Dict[str, Any]]:
        """
        Aggregate topic performance across all assessments
        Returns topics marked as Strong (>70%), Moderate (50-70%), Weak (<50%)
        """
        # Get all questions for this teacher
        questions = await self.db.questions.find({
            "owner_teacher_id": owner_teacher_id
        }, {"_id": 0}).to_list(1000)
        
        topic_stats = {}
        
        for question in questions:
            topic = question.get("topic") or question.get("subject", "General")
            max_marks = question.get("max_marks", 100)
            
            # Get assessments using this question
            assessments = await self.db.assessments.find({
                "question_id": question.get("id")
            }, {"_id": 0, "id": 1}).to_list(100)
            
            for assessment in assessments:
                # Get all marked attempts
                attempts = await self.db.attempts.find({
                    "assessment_id": assessment.get("id"),
                    "status": "marked"
                }, {"_id": 0, "score": 1, "student_name": 1}).to_list(1000)
                
                for attempt in attempts:
                    score = attempt.get("score", 0)
                    percentage = (score / max_marks * 100) if max_marks > 0 else 0
                    
                    if topic not in topic_stats:
                        topic_stats[topic] = {
                            "scores": [],
                            "students": set()
                        }
                    
                    topic_stats[topic]["scores"].append(percentage)
                    if percentage < 50:
                        topic_stats[topic]["students"].add(attempt.get("student_name"))
        
        # Calculate topic performance
        results = []
        for topic, data in topic_stats.items():
            if data["scores"]:
                avg = statistics.mean(data["scores"])
                if avg >= 70:
                    status = "strong"
                elif avg >= 50:
                    status = "moderate"
                else:
                    status = "weak"
                
                results.append({
                    "topic": topic,
                    "average_percentage": round(avg, 1),
                    "status": status,
                    "total_attempts": len(data["scores"]),
                    "struggling_students": list(data["students"])
                })
        
        # Sort by average (weakest first)
        results.sort(key=lambda x: x["average_percentage"])
        return results
    
    async def get_assessment_analytics(self, assessment_id: str) -> Dict[str, Any]:
        """
        Get detailed analytics for a single assessment
        """
        assessment = await self.db.assessments.find_one({"id": assessment_id}, {"_id": 0})
        if not assessment:
            return None
        
        question = await self.db.questions.find_one({"id": assessment.get("question_id")}, {"_id": 0})
        max_marks = question.get("max_marks", 100) if question else 100
        
        # Get all marked attempts
        attempts = await self.db.attempts.find({
            "assessment_id": assessment_id,
            "status": "marked"
        }, {"_id": 0}).to_list(1000)
        
        if not attempts:
            return {
                "assessment_id": assessment_id,
                "total_submissions": 0,
                "average_score": 0,
                "average_percentage": 0,
                "highest_score": 0,
                "lowest_score": 0,
                "difficulty_index": 0,
                "distribution": [],
                "subject": question.get("subject") if question else "Unknown"
            }
        
        scores = [a.get("score", 0) for a in attempts]
        percentages = [(s / max_marks * 100) if max_marks > 0 else 0 for s in scores]
        
        # Calculate distribution buckets
        distribution = {
            "0-20": 0,
            "21-40": 0,
            "41-60": 0,
            "61-80": 0,
            "81-100": 0
        }
        
        for p in percentages:
            if p <= 20:
                distribution["0-20"] += 1
            elif p <= 40:
                distribution["21-40"] += 1
            elif p <= 60:
                distribution["41-60"] += 1
            elif p <= 80:
                distribution["61-80"] += 1
            else:
                distribution["81-100"] += 1
        
        difficulty_index = await self.calculate_difficulty_index(assessment_id)
        
        return {
            "assessment_id": assessment_id,
            "subject": question.get("subject") if question else "Unknown",
            "topic": question.get("topic") if question else None,
            "max_marks": max_marks,
            "total_submissions": len(attempts),
            "average_score": round(statistics.mean(scores), 1),
            "average_percentage": round(statistics.mean(percentages), 1),
            "highest_score": max(scores),
            "lowest_score": min(scores),
            "median_score": round(statistics.median(scores), 1),
            "std_deviation": round(statistics.stdev(scores), 1) if len(scores) > 1 else 0,
            "difficulty_index": difficulty_index,
            "distribution": [{"range": k, "count": v} for k, v in distribution.items()],
            "created_at": assessment.get("created_at")
        }
    
    async def get_student_profile(self, student_name: str, owner_teacher_id: str) -> Dict[str, Any]:
        """
        Get comprehensive analytics profile for a student
        """
        # Get all submissions for this student
        attempts = await self.db.attempts.find({
            "student_name": student_name,
            "owner_teacher_id": owner_teacher_id
        }, {"_id": 0}).sort("submitted_at", -1).to_list(100)
        
        if not attempts:
            return None
        
        # Enrich with assessment and question data
        submissions = []
        topic_scores = {}
        
        for attempt in attempts:
            assessment = await self.db.assessments.find_one({"id": attempt.get("assessment_id")}, {"_id": 0})
            question = await self.db.questions.find_one({"id": assessment.get("question_id")}, {"_id": 0}) if assessment else None
            
            max_marks = question.get("max_marks", 100) if question else 100
            score = attempt.get("score", 0)
            percentage = (score / max_marks * 100) if max_marks > 0 else 0
            
            subject = question.get("subject", "Unknown") if question else "Unknown"
            topic = question.get("topic") or subject
            
            submissions.append({
                "attempt_id": attempt.get("attempt_id"),
                "assessment_id": attempt.get("assessment_id"),
                "subject": subject,
                "topic": topic,
                "score": score,
                "max_marks": max_marks,
                "percentage": round(percentage, 1),
                "status": attempt.get("status"),
                "submitted_at": attempt.get("submitted_at"),
                "www": attempt.get("www"),
                "next_steps": attempt.get("next_steps"),
                "feedback_released": attempt.get("feedback_released", False)
            })
            
            # Track topic performance
            if topic not in topic_scores:
                topic_scores[topic] = []
            topic_scores[topic].append(percentage)
        
        # Calculate weak topics
        weak_topics = []
        for topic, scores in topic_scores.items():
            avg = statistics.mean(scores)
            if avg < 50:
                weak_topics.append({
                    "topic": topic,
                    "average": round(avg, 1),
                    "attempts": len(scores)
                })
        
        # Get support status
        support_data = await self.check_needs_support(student_name, owner_teacher_id)
        trend_data = await self.calculate_student_trend(student_name, owner_teacher_id)
        
        # Calculate overall average
        all_percentages = [s["percentage"] for s in submissions if s["status"] == "marked"]
        overall_average = statistics.mean(all_percentages) if all_percentages else 0
        
        return {
            "student_name": student_name,
            "total_submissions": len(submissions),
            "marked_submissions": len([s for s in submissions if s["status"] == "marked"]),
            "overall_average": round(overall_average, 1),
            "trend": trend_data.get("trend"),
            "trend_slope": trend_data.get("slope"),
            "needs_support": support_data.get("needs_support"),
            "support_reasons": support_data.get("reasons", []),
            "weak_topics": weak_topics,
            "submissions": submissions,
            "recent_scores": trend_data.get("recent_scores", [])
        }
    
    async def get_class_overview(self, owner_teacher_id: str) -> Dict[str, Any]:
        """
        Get class-level analytics overview
        """
        # Get all unique students
        pipeline = [
            {"$match": {"owner_teacher_id": owner_teacher_id, "status": "marked"}},
            {"$group": {"_id": "$student_name"}},
        ]
        student_docs = await self.db.attempts.aggregate(pipeline).to_list(1000)
        students = [doc["_id"] for doc in student_docs]
        
        # Analyze each student
        underperforming = []
        improving = []
        declining = []
        all_students_data = []
        
        for student_name in students:
            support_data = await self.check_needs_support(student_name, owner_teacher_id)
            trend_data = await self.calculate_student_trend(student_name, owner_teacher_id)
            
            student_info = {
                "student_name": student_name,
                "average": support_data.get("average_percentage", 0),
                "trend": trend_data.get("trend"),
                "needs_support": support_data.get("needs_support"),
                "reasons": support_data.get("reasons", [])
            }
            all_students_data.append(student_info)
            
            if support_data.get("average_percentage", 100) < 50:
                underperforming.append(student_info)
            
            if trend_data.get("trend") == "improving":
                improving.append(student_info)
            elif trend_data.get("trend") == "declining":
                declining.append(student_info)
        
        # Get topic performance
        topic_performance = await self.get_topic_performance(owner_teacher_id)
        weak_topics = [t for t in topic_performance if t["status"] == "weak"]
        strong_topics = [t for t in topic_performance if t["status"] == "strong"]
        
        # Get assessment count
        assessments = await self.db.assessments.find({
            "owner_teacher_id": owner_teacher_id
        }, {"_id": 0}).to_list(1000)
        
        total_attempts = await self.db.attempts.count_documents({
            "owner_teacher_id": owner_teacher_id,
            "status": "marked"
        })
        
        return {
            "total_students": len(students),
            "total_assessments": len(assessments),
            "total_submissions": total_attempts,
            "underperforming_count": len(underperforming),
            "improving_count": len(improving),
            "declining_count": len(declining),
            "underperforming_students": underperforming,
            "improving_students": improving,
            "declining_students": declining,
            "weak_topics": weak_topics,
            "strong_topics": strong_topics,
            "all_students": all_students_data
        }
    
    async def generate_ai_intervention_summary(self, owner_teacher_id: str, llm_chat) -> str:
        """
        Generate AI-powered intervention strategy recommendation
        """
        overview = await self.get_class_overview(owner_teacher_id)
        
        # Build context for AI
        context = f"""
        Class Analytics Summary:
        - Total Students: {overview['total_students']}
        - Students Underperforming (<50%): {overview['underperforming_count']}
        - Students with Improving Trend: {overview['improving_count']}
        - Students with Declining Trend: {overview['declining_count']}
        
        Underperforming Students:
        {', '.join([f"{s['student_name']} ({s['average']}%)" for s in overview['underperforming_students'][:10]])}
        
        Declining Students:
        {', '.join([f"{s['student_name']} ({s['average']}%)" for s in overview['declining_students'][:10]])}
        
        Weak Topics (Class Average < 50%):
        {', '.join([f"{t['topic']} ({t['average_percentage']}%)" for t in overview['weak_topics'][:5]])}
        
        Strong Topics (Class Average > 70%):
        {', '.join([f"{t['topic']} ({t['average_percentage']}%)" for t in overview['strong_topics'][:5]])}
        """
        
        prompt = f"""Based on the following class analytics data, provide a concise intervention strategy recommendation for the teacher. Focus on:
1. Which students need immediate support
2. Which topics need class-wide revision
3. Specific actionable recommendations

{context}

Provide a 2-3 sentence summary that a teacher can act on immediately. Be specific about student names and topics where relevant."""

        try:
            # response = await llm_chat.send_message_async(UserMessage(text=prompt))
            # # Extract text from response
            # response_text = response if isinstance(response, str) else str(response)
            # return response_text
            # Mock response for now
            return "AI insights temporarily disabled. Please review the analytics data manually."
        except Exception as e:
            # Fallback to rule-based summary
            declining_names = [s['student_name'] for s in overview['declining_students'][:5]]
            weak_topic_names = [t['topic'] for t in overview['weak_topics'][:3]]
            
            summary_parts = []
            if declining_names:
                summary_parts.append(f"{len(declining_names)} student(s) showing declining performance: {', '.join(declining_names)}.")
            if weak_topic_names:
                summary_parts.append(f"Class is struggling with: {', '.join(weak_topic_names)}. Recommend targeted revision.")
            if overview['underperforming_count'] > 0:
                summary_parts.append(f"{overview['underperforming_count']} student(s) need support (average < 50%).")
            
            return " ".join(summary_parts) if summary_parts else "No immediate interventions needed. Class performance is stable."
    
    async def get_heatmap_data(self, owner_teacher_id: str) -> Dict[str, Any]:
        """
        Generate heatmap data: Students x Assessments = Score percentage
        """
        # Get all assessments
        assessments = await self.db.assessments.find({
            "owner_teacher_id": owner_teacher_id
        }, {"_id": 0}).sort("created_at", 1).to_list(100)
        
        # Get unique students
        pipeline = [
            {"$match": {"owner_teacher_id": owner_teacher_id}},
            {"$group": {"_id": "$student_name"}},
        ]
        student_docs = await self.db.attempts.aggregate(pipeline).to_list(1000)
        students = sorted([doc["_id"] for doc in student_docs])
        
        # Build assessment info
        assessment_info = []
        for assessment in assessments:
            question = await self.db.questions.find_one({"id": assessment.get("question_id")}, {"_id": 0})
            assessment_info.append({
                "id": assessment.get("id"),
                "subject": question.get("subject", "Unknown") if question else "Unknown",
                "max_marks": question.get("max_marks", 100) if question else 100,
                "date": assessment.get("created_at")
            })
        
        # Build heatmap matrix
        heatmap = []
        for student in students:
            row = {"student": student, "scores": []}
            for a_info in assessment_info:
                attempt = await self.db.attempts.find_one({
                    "assessment_id": a_info["id"],
                    "student_name": student
                }, {"_id": 0, "score": 1, "status": 1})
                
                if attempt and attempt.get("status") == "marked":
                    score = attempt.get("score", 0)
                    percentage = (score / a_info["max_marks"] * 100) if a_info["max_marks"] > 0 else 0
                    row["scores"].append({
                        "assessment_id": a_info["id"],
                        "percentage": round(percentage, 1),
                        "status": "green" if percentage >= 70 else "amber" if percentage >= 50 else "red"
                    })
                else:
                    row["scores"].append({
                        "assessment_id": a_info["id"],
                        "percentage": None,
                        "status": "none"
                    })
            heatmap.append(row)
        
        return {
            "assessments": assessment_info,
            "students": students,
            "heatmap": heatmap
        }
