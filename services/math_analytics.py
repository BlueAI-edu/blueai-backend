"""Enhanced Analytics Service for BlueAI - Math Performance Tracking"""
from typing import Dict, List, Any
from collections import defaultdict
import statistics


class MathAnalyticsEngine:
    """Advanced analytics for math question performance and student progress"""
    
    def analyze_math_performance(self, submissions: List[Dict]) -> Dict[str, Any]:
        """
        Analyze performance on math questions with LaTeX and working
        
        Returns comprehensive analytics including:
        - LaTeX usage patterns
        - Working quality metrics
        - Equivalence check success rates
        - Common error patterns
        """
        
        total = len(submissions)
        if total == 0:
            return self._empty_analytics()
        
        # Categorize by answer type
        by_type = defaultdict(list)
        latex_usage = 0
        working_provided = 0
        equivalence_checked = 0
        equivalence_correct = 0
        
        for sub in submissions:
            answer_text = sub.get('answer_text', '')
            answer_type = sub.get('answer_type', 'text')
            show_working = sub.get('show_working', '')
            
            by_type[answer_type].append(sub)
            
            # LaTeX usage
            if '$' in answer_text:
                latex_usage += 1
            
            # Working provided
            if show_working and len(show_working.strip()) > 10:
                working_provided += 1
            
            # Equivalence checking
            if sub.get('equivalence_checked'):
                equivalence_checked += 1
                if sub.get('score', 0) > 0:
                    equivalence_correct += 1
        
        # Calculate percentages
        latex_usage_pct = (latex_usage / total) * 100 if total > 0 else 0
        working_provided_pct = (working_provided / total) * 100 if total > 0 else 0
        equivalence_success_rate = (equivalence_correct / equivalence_checked) * 100 if equivalence_checked > 0 else 0
        
        # Analyze by question type
        performance_by_type = {}
        for q_type, subs in by_type.items():
            scores = [s.get('score', 0) for s in subs]
            performance_by_type[q_type] = {
                'count': len(subs),
                'avg_score': statistics.mean(scores) if scores else 0,
                'median_score': statistics.median(scores) if scores else 0,
                'pass_rate': sum(1 for s in scores if s >= 50) / len(scores) * 100 if scores else 0
            }
        
        # Working quality analysis
        working_quality = self._analyze_working_quality(submissions)
        
        # Common mistakes in math
        common_mistakes = self._identify_math_mistakes(submissions)
        
        return {
            'overview': {
                'total_submissions': total,
                'latex_usage_percentage': round(latex_usage_pct, 1),
                'working_provided_percentage': round(working_provided_pct, 1),
                'equivalence_checked': equivalence_checked,
                'equivalence_success_rate': round(equivalence_success_rate, 1)
            },
            'performance_by_type': performance_by_type,
            'working_quality': working_quality,
            'common_mistakes': common_mistakes,
            'recommendations': self._generate_recommendations(
                latex_usage_pct,
                working_provided_pct,
                performance_by_type
            )
        }
    
    def _analyze_working_quality(self, submissions: List[Dict]) -> Dict[str, Any]:
        """Analyze quality of student working"""
        with_working = [s for s in submissions if s.get('show_working', '').strip()]
        
        if not with_working:
            return {'analysis': 'No working data available'}
        
        # Analyze working length (indicator of detail)
        working_lengths = [len(s.get('show_working', '')) for s in with_working]
        
        # Count structured working (has steps, given, etc.)
        structured = sum(1 for s in with_working 
                        if '**Step' in s.get('show_working', '') 
                        or '**Given' in s.get('show_working', ''))
        
        # LaTeX in working
        latex_in_working = sum(1 for s in with_working 
                              if '$' in s.get('show_working', ''))
        
        return {
            'submissions_with_working': len(with_working),
            'average_length': round(statistics.mean(working_lengths), 0),
            'structured_working_pct': round((structured / len(with_working)) * 100, 1),
            'latex_usage_in_working_pct': round((latex_in_working / len(with_working)) * 100, 1),
            'quality_score': self._calculate_working_quality_score(
                structured, latex_in_working, len(with_working), working_lengths
            )
        }
    
    def _calculate_working_quality_score(self, structured: int, latex_usage: int, 
                                         total: int, lengths: List[int]) -> int:
        """Calculate overall working quality score (0-100)"""
        if total == 0:
            return 0
        
        # Components of quality
        structure_score = (structured / total) * 40  # 40% weight
        latex_score = (latex_usage / total) * 30     # 30% weight
        
        # Length score (ideal range 200-500 characters)
        avg_length = statistics.mean(lengths)
        if avg_length < 100:
            length_score = (avg_length / 100) * 30
        elif avg_length > 500:
            length_score = 30 - ((avg_length - 500) / 100) * 5
        else:
            length_score = 30
        
        length_score = max(0, min(30, length_score))  # Cap between 0-30
        
        return round(structure_score + latex_score + length_score)
    
    def _identify_math_mistakes(self, submissions: List[Dict]) -> List[Dict[str, Any]]:
        """Identify common mathematical mistakes"""
        mistakes = []
        
        # Count incorrect submissions
        incorrect = [s for s in submissions if s.get('score', 0) < 50]
        
        if len(incorrect) < 3:  # Need at least 3 to identify patterns
            return []
        
        # Pattern 1: Missing units
        missing_units = sum(1 for s in incorrect 
                           if not any(unit in s.get('answer_text', '').lower() 
                                     for unit in ['m/s', 'kg', 'n', 'j', 'w', 'mol', '°c', 'm', 's']))
        
        if missing_units > len(incorrect) * 0.3:  # 30% threshold
            mistakes.append({
                'pattern': 'Missing units in answers',
                'frequency': missing_units,
                'percentage': round((missing_units / len(incorrect)) * 100, 1),
                'severity': 'medium'
            })
        
        # Pattern 2: Sign errors (if equivalence data available)
        sign_errors = sum(1 for s in incorrect 
                         if 'sign' in s.get('feedback', '').lower() 
                         or 'negative' in s.get('feedback', '').lower())
        
        if sign_errors > len(incorrect) * 0.2:
            mistakes.append({
                'pattern': 'Sign errors (positive/negative)',
                'frequency': sign_errors,
                'percentage': round((sign_errors / len(incorrect)) * 100, 1),
                'severity': 'high'
            })
        
        # Pattern 3: No working shown but answer wrong
        no_working_wrong = sum(1 for s in incorrect 
                              if not s.get('show_working', '').strip())
        
        if no_working_wrong > len(incorrect) * 0.4:
            mistakes.append({
                'pattern': 'No working shown for incorrect answers',
                'frequency': no_working_wrong,
                'percentage': round((no_working_wrong / len(incorrect)) * 100, 1),
                'severity': 'low',
                'recommendation': 'Encourage students to show working for partial credit'
            })
        
        return mistakes
    
    def _generate_recommendations(self, latex_usage: float, working_usage: float, 
                                 performance_by_type: Dict) -> List[str]:
        """Generate actionable recommendations"""
        recommendations = []
        
        # LaTeX recommendations
        if latex_usage < 30:
            recommendations.append({
                'category': 'LaTeX Usage',
                'issue': f'Only {latex_usage:.0f}% of students using LaTeX formatting',
                'action': 'Provide LaTeX tutorial or examples',
                'priority': 'medium'
            })
        elif latex_usage > 80:
            recommendations.append({
                'category': 'LaTeX Usage',
                'issue': f'Excellent LaTeX adoption ({latex_usage:.0f}%)',
                'action': 'Continue encouraging proper mathematical notation',
                'priority': 'low'
            })
        
        # Working recommendations
        if working_usage < 40:
            recommendations.append({
                'category': 'Show Working',
                'issue': f'Only {working_usage:.0f}% of students showing working',
                'action': 'Emphasize partial credit availability and require working for multi-step questions',
                'priority': 'high'
            })
        
        # Performance by type
        for q_type, perf in performance_by_type.items():
            if perf['pass_rate'] < 50:
                recommendations.append({
                    'category': 'Question Type Performance',
                    'issue': f'Low pass rate ({perf["pass_rate"]:.0f}%) on {q_type} questions',
                    'action': f'Provide additional practice or intervention on {q_type}',
                    'priority': 'high'
                })
        
        return recommendations
    
    def _empty_analytics(self) -> Dict[str, Any]:
        """Return empty analytics structure"""
        return {
            'overview': {
                'total_submissions': 0,
                'latex_usage_percentage': 0,
                'working_provided_percentage': 0,
                'equivalence_checked': 0,
                'equivalence_success_rate': 0
            },
            'performance_by_type': {},
            'working_quality': {'analysis': 'No data available'},
            'common_mistakes': [],
            'recommendations': []
        }


# Global instance
math_analytics_engine = MathAnalyticsEngine()
