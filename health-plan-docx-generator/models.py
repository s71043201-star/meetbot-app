from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class DoctorPrescription:
    """每位醫師的處方資料"""
    medical_institution: str  # 醫療機構
    doctor_name: str  # 開立醫師
    exercise: int = 0  # 運動處方 開立份數
    nutrition: int = 0  # 營養處方
    emotion: int = 0  # 情緒調適處方
    social: int = 0  # 社會處方
    exercise_exec: int = 0  # 運動處方 執行份數
    nutrition_exec: int = 0  # 營養處方 執行份數
    emotion_exec: int = 0  # 情緒調適處方 執行份數
    social_exec: int = 0  # 社會處方 執行份數
    prescription_fee: int = 0   # 處方費總金額
    execution_fee: int = 0      # 處方執行費總金額
    patients: List["PatientRecord"] = field(default_factory=list)  # 此醫師「開立」處方的民眾（處方費明細用）
    execution_patients: List["PatientRecord"] = field(default_factory=list)  # 此醫師處方「已執行」的民眾（執行費明細用）


@dataclass
class HealthManagement:
    """健康管理費資料"""
    medical_institution: str
    clinic_person: str  # 診所人員
    prescription_people: int = 0  # 開立處方人數
    prescription_count: int = 0  # 開立份數
    is_qualified: bool = False  # 是否達標
    patients: List["PatientRecord"] = field(default_factory=list)  # 此診所的民眾明細


@dataclass
class PatientRecord:
    """民眾明細"""
    name: str  # 民眾姓名
    id_number: str  # 身分證字號
    birth_date: str  # 出生年月日 yyyy/mm/dd
    prescriber: str  # 處方人員姓名
    exec_date: str = ""  # 執行日期
    issue_date: str = ""  # 開立日期
    prescription_type: str = ""  # 處方類型（運動/營養/情緒調適/社會 處方）


@dataclass
class ReceiptInfo:
    """領據資訊"""
    recipient_name: str = ""  # 具領人
    id_number: str = ""  # 身分證字號
    address: str = ""  # 戶籍地址
    phone: str = ""  # 聯絡電話
    account_name: str = ""  # 戶名
    bank_branch: str = ""  # 銀行及分行
    bank_code: str = ""  # 銀行代碼
    account_number: str = ""  # 帳號
    amount: int = 0  # 應付金額
    role: str = ""  # 角色：醫師 / 課程老師 / 診所行政人員
    clinic_name: str = ""  # 所屬診所（診所行政人員用）
    email: str = ""  # Email（寄送核銷文件用）


@dataclass
class ExecutorData:
    """執行人員端資料"""
    executor_name: str
    prescription_type: str  # 處方類型（多類型時為主要類型,僅作備註用）
    service_count: int = 0  # 全類型合計服務人次
    type_counts: Dict[str, int] = field(default_factory=dict)  # {運動處方: N, ...}
    patients: List[PatientRecord] = field(default_factory=list)  # 已按類型排序
    receipt: Optional[ReceiptInfo] = None


@dataclass
class AllData:
    """所有輸入資料"""
    report_year: int  # 民國年
    report_month: int  # 月份
    doctors: List[DoctorPrescription] = field(default_factory=list)
    health_mgmts: List[HealthManagement] = field(default_factory=list)
    patients: List[PatientRecord] = field(default_factory=list)
    clinic_receipt: Optional[ReceiptInfo] = None
    executors: List[ExecutorData] = field(default_factory=list)
    min_prescriptions: int = 0  # 健管費最低份數門檻（UI 傳入，供總表註解顯示）
